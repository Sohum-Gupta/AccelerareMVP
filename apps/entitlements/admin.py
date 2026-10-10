from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import AutocompleteSelect
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import Account

from . import services
from .models import Entitlement

# Licences are granted, upgraded and revoked through services.py so the rules sit
# in one place. The add form picks an account (the licence goes to its person);
# afterwards only the tier can be changed. There is no delete: revoke instead.


class GrantForm(forms.ModelForm):
    account = forms.ModelChoiceField(
        Account.objects.all(), help_text="The licence goes to this account's person."
    )

    class Meta:
        model = Entitlement
        fields = ("account", "tier", "source")


class UnusedLicenceFilter(admin.SimpleListFilter):
    """Licences someone holds but has not started the survey with, by how long."""

    title = "unused licences"
    parameter_name = "unused"

    def lookups(self, request, model_admin):
        return [
            ("any", "Unused (any age)"),
            ("7", "Unused for 7+ days"),
            ("30", "Unused for 30+ days"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value not in ("any", "7", "30"):
            return queryset
        # Active, and no attempt has consumed it.
        queryset = queryset.filter(revoked_at__isnull=True, response__isnull=True)
        if value != "any":
            queryset = queryset.filter(granted_at__lte=timezone.now() - timedelta(days=int(value)))
        return queryset


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ("id", "logins", "tier", "source", "granted_at", "granted_by", "active")
    list_filter = (UnusedLicenceFilter, "tier", "source")
    search_fields = (
        "person__accounts__email",
        "person__accounts__contact_points__value_normalised",
        "person__accounts__contact_points__value_display",
    )
    list_select_related = ("granted_by",)
    actions = ["revoke_selected"]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("person__accounts")

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = GrantForm
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            # A search box instead of a dropdown of every account. It searches the
            # way the Accounts page does (email or phone); granted_by is only the
            # Account relation the admin's search endpoint needs to find that page.
            form.base_fields["account"] = forms.ModelChoiceField(
                Account.objects.all(),
                help_text=GrantForm.base_fields["account"].help_text,
                widget=AutocompleteSelect(
                    Entitlement._meta.get_field("granted_by"), self.admin_site
                ),
            )
        return form

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("account", "tier", "source")
        return ("person", "tier", "source", "granted_by", "granted_at", "revoked_at")

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("person", "source", "granted_by", "granted_at", "revoked_at")

    @admin.display(description="Logins")
    def logins(self, entitlement):
        return ", ".join(a.email for a in entitlement.person.accounts.all())

    @admin.display(boolean=True, description="Active")
    def active(self, entitlement):
        return entitlement.is_active

    def save_model(self, request, obj, form, change):
        try:
            if change:
                services.change_tier(obj, form.cleaned_data["tier"])
            else:
                account = form.cleaned_data["account"]
                created = services.grant_individual(
                    account.person,
                    form.cleaned_data["tier"],
                    form.cleaned_data["source"],
                    request.user,
                )
                obj.pk = created.pk  # so the admin's redirect finds the new row
        except ValidationError as error:
            self.message_user(request, " ".join(error.messages), messages.ERROR)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Revoke the selected licences", permissions=["change"])
    def revoke_selected(self, request, queryset):
        revoked = drafts = 0
        for entitlement in queryset:
            if entitlement.is_active:
                _, draft_deleted = services.revoke(entitlement)
                # The service bypasses the admin's own history, so record who did it.
                message = "Revoked"
                if draft_deleted:
                    message = "Revoked; the unfinished attempt on it was deleted"
                    drafts += 1
                self.log_change(request, entitlement, message)
                revoked += 1
        text = f"Revoked {revoked} licence(s)."
        if drafts:
            text += f" Deleted {drafts} unfinished attempt(s) that could no longer continue."
        self.message_user(request, text, messages.SUCCESS)
