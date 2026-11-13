from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import AutocompleteSelect
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import Account
from apps.enterprises.models import Membership

from . import services
from .models import Entitlement

# Licences are granted, upgraded and revoked through services.py so the rules sit
# in one place. The add form picks either an account (a personal licence, which
# goes to the account's person) or a membership (a licence for that
# organization); afterwards only the tier can be changed. There is no delete:
# revoke instead.

ACCOUNT_HELP = (
    "A personal licence: the person takes the survey for themselves and no organization "
    "sees it. Search by email or phone. Leave empty for an organization licence."
)
MEMBERSHIP_HELP = (
    "A licence for an organization: the member takes the survey for that organization, "
    "whose admins see that it was taken (never the answers). Search by the member's "
    "email or name, or the organization's name. Leave empty for a personal licence."
)


class GrantForm(forms.ModelForm):
    account = forms.ModelChoiceField(Account.objects.all(), required=False, help_text=ACCOUNT_HELP)
    membership = forms.ModelChoiceField(
        Membership.objects.all(), required=False, help_text=MEMBERSHIP_HELP
    )

    class Meta:
        model = Entitlement
        fields = ("account", "membership", "tier", "source")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Staff grant by hand or record a purchase. "From the organization's
        # stock" is not offered: those are given by the organization's admin.
        self.fields["source"].choices = [
            (value, label)
            for value, label in self.fields["source"].choices
            if value == "" or value in services.GRANTABLE_SOURCES
        ]

    def clean(self):
        cleaned = super().clean()
        account, membership = cleaned.get("account"), cleaned.get("membership")
        if bool(account) == bool(membership):
            raise forms.ValidationError(
                "Choose an account (a personal licence) or a membership (a licence for an "
                "organization): one of the two, not both."
            )
        if membership is not None and not membership.is_active:
            self.add_error("membership", services.DEACTIVATED_MEMBERSHIP)
        return cleaned


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


class ContextFilter(admin.SimpleListFilter):
    """Personal licences, or licences for an organization."""

    title = "used for"
    parameter_name = "context"

    def lookups(self, request, model_admin):
        return [("personal", "Personal"), ("organization", "An organization")]

    def queryset(self, request, queryset):
        if self.value() == "personal":
            return queryset.filter(membership__isnull=True)
        if self.value() == "organization":
            return queryset.filter(membership__isnull=False)
        return queryset


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "logins",
        "context",
        "tier",
        "source",
        "granted_at",
        "granted_by",
        "active",
    )
    list_filter = (UnusedLicenceFilter, ContextFilter, "tier", "source")
    search_fields = (
        "person__accounts__email",
        "person__accounts__contact_points__value_normalised",
        "person__accounts__contact_points__value_display",
        "membership__account__email",
        "membership__enterprise__name",
    )
    list_select_related = ("granted_by", "membership__account", "membership__enterprise")
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
                required=False,
                help_text=ACCOUNT_HELP,
                widget=AutocompleteSelect(
                    Entitlement._meta.get_field("granted_by"), self.admin_site
                ),
            )
            # The same for memberships; it searches the way the Memberships page does.
            form.base_fields["membership"] = forms.ModelChoiceField(
                Membership.objects.all(),
                required=False,
                help_text=MEMBERSHIP_HELP,
                widget=AutocompleteSelect(
                    Entitlement._meta.get_field("membership"), self.admin_site
                ),
            )
        return form

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("account", "membership", "tier", "source")
        owner = "person" if obj.is_personal else "membership"
        return (owner, "tier", "source", "granted_by", "granted_at", "revoked_at")

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("person", "membership", "source", "granted_by", "granted_at", "revoked_at")

    @admin.display(description="Logins")
    def logins(self, entitlement):
        if entitlement.membership_id is not None:
            return entitlement.membership.account.email
        return ", ".join(a.email for a in entitlement.person.accounts.all())

    @admin.display(description="Used for")
    def context(self, entitlement):
        if entitlement.membership_id is not None:
            return entitlement.membership.enterprise.name
        return "Personal"

    @admin.display(boolean=True, description="Active")
    def active(self, entitlement):
        return entitlement.is_active

    def save_model(self, request, obj, form, change):
        try:
            if change:
                services.change_tier(obj, form.cleaned_data["tier"])
            else:
                tier, source = form.cleaned_data["tier"], form.cleaned_data["source"]
                membership = form.cleaned_data["membership"]
                if membership is not None:
                    created = services.grant_for_membership(membership, tier, source, request.user)
                else:
                    person = form.cleaned_data["account"].person
                    created = services.grant_individual(person, tier, source, request.user)
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
