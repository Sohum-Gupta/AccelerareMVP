from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.auth.admin import UserAdmin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from . import erasure, services
from .models import Account, ContactPoint, Person

# Every email lives in two tables (ours and allauth's) and services.py keeps them
# in step. So the admin only reads contact points, and changes them through the
# same service functions the profile page uses. It has no edit, add or delete
# form for them, and the login email on an account is read-only for the same
# reason.


class ReadOnlyContactPoints(admin.TabularInline):
    model = ContactPoint
    extra = 0
    can_delete = False
    fields = ("kind", "value_display", "is_primary", "verified_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class EraseForm(forms.Form):
    """Typing the email is the "are you sure"; the reason goes in the admin history."""

    email = forms.CharField(
        label="Type the account's email to confirm",
        widget=forms.TextInput(attrs={"size": 40, "autocomplete": "off"}),
    )
    reason = forms.CharField(
        label="Reason",
        min_length=5,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "cols": 40}),
        help_text="Why this is being erased (for example 'deletion request, ticket 123'). "
        "Do not type the person's email or phone: this note is kept.",
    )

    def __init__(self, *args, account, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account

    def clean_email(self):
        typed = self.cleaned_data["email"].strip().lower()
        if typed != self.account.email.lower():
            raise forms.ValidationError("That is not this account's email.")
        return typed


@admin.register(Account)
class AccountAdmin(UserAdmin):
    """
    Django's stock UserAdmin assumes a username field, so the fieldsets and
    search/ordering are redefined around email. It keeps the password-change
    form and the hashed-password display. New accounts come from sign-up or
    `createsuperuser`, which also create the Person and contacts; the admin's
    own add form would not, so it is switched off.
    """

    list_display = ("email", "is_active", "is_staff", "is_superuser", "erased", "created_at")
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        ("anonymised_at", admin.EmptyFieldListFilter),
    )
    search_fields = (
        "email",
        "contact_points__value_normalised",
        "contact_points__value_display",
    )
    ordering = ("email",)
    readonly_fields = ("email", "person", "created_at", "last_login", "anonymised_at")
    inlines = [ReadOnlyContactPoints]

    fieldsets = (
        (None, {"fields": ("email", "person", "password")}),
        ("Status", {"fields": ("is_active", "is_staff", "is_superuser", "anonymised_at")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
        ("Dates", {"fields": ("created_at", "last_login")}),
    )

    def has_add_permission(self, request):
        return False

    # The stock delete would skip the erase rules (what is kept, what the history
    # shows). Erasing goes through the button below instead.
    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(boolean=True, description="Erased", ordering="anonymised_at")
    def erased(self, account):
        return account.anonymised_at is not None

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and obj.anonymised_at is not None:
            # Nothing on an erased account can be switched back on.
            fields = (
                *fields,
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            )
        return fields

    def get_urls(self):
        custom = path(
            "<path:object_id>/erase/",
            self.admin_site.admin_view(self.erase_view),
            name="accounts_account_erase",
        )
        return [custom, *super().get_urls()]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        account = self.get_object(request, object_id)
        if request.user.is_superuser and account is not None and account.anonymised_at is None:
            extra_context["erase_url"] = reverse("admin:accounts_account_erase", args=[object_id])
        return super().change_view(request, object_id, form_url, extra_context)

    def erase_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        account = get_object_or_404(Account, pk=object_id)
        back = reverse("admin:accounts_account_change", args=[account.pk])
        try:
            plan = erasure.plan_erasure(account, by=request.user)
        except ValidationError as error:
            self.message_user(request, " ".join(error.messages), messages.ERROR)
            return redirect(back)

        form = EraseForm(request.POST or None, account=account)
        if request.method == "POST" and form.is_valid():
            pk = account.pk
            try:
                done = erasure.erase_account(account, by=request.user)
            except ValidationError as error:
                self.message_user(request, " ".join(error.messages), messages.ERROR)
                return redirect(back)
            # Logged by hand with a label that has no email in it; the admin's
            # own logging would write the email into the history.
            LogEntry.objects.create(
                user=request.user,
                content_type=ContentType.objects.get_for_model(Account),
                object_id=str(pk),
                object_repr=f"Account #{pk}",
                action_flag=DELETION if done.action == erasure.DELETE else CHANGE,
                change_message=f"Erased. {form.cleaned_data['reason']}",
            )
            if done.action == erasure.DELETE:
                self.message_user(request, f"Account #{pk} was permanently deleted.")
                return redirect("admin:accounts_account_changelist")
            self.message_user(
                request, f"Account #{pk} was erased: the person is removed and the results kept."
            )
            return redirect(back)

        context = {
            **self.admin_site.each_context(request),
            "title": "Erase account",
            "opts": self.model._meta,
            "account": account,
            "plan": plan,
            "form": form,
        }
        return TemplateResponse(request, "admin/accounts/account/erase.html", context)


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("id", "logins", "created_at", "merged_into")
    search_fields = (
        "accounts__email",
        "accounts__contact_points__value_normalised",
        "accounts__contact_points__value_display",
    )
    readonly_fields = ("created_at", "merged_into")

    @admin.display(description="Logins")
    def logins(self, person):
        return ", ".join(a.email for a in person.accounts.all())

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("accounts")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ContactPoint)
class ContactPointAdmin(admin.ModelAdmin):
    list_display = ("value_display", "kind", "account", "verified", "is_primary", "created_at")
    list_filter = ("kind", "is_primary")
    search_fields = ("value_normalised", "value_display", "account__email")
    list_select_related = ("account",)
    actions = ["make_primary", "remove"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    @admin.display(boolean=True, description="Verified")
    def verified(self, contact):
        return contact.verified_at is not None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _run(self, request, contacts, action, done):
        for contact in contacts:
            try:
                action(contact.account, contact)
            except ValidationError as error:
                self.message_user(request, f"{contact}: {' '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{contact}: {done}.", messages.SUCCESS)

    @admin.action(
        description="Make the selected email its account's primary", permissions=["change"]
    )
    def make_primary(self, request, queryset):
        self._run(request, queryset, services.make_primary, "now the primary email")

    @admin.action(
        description="Remove the selected contacts (not primaries)", permissions=["change"]
    )
    def remove(self, request, queryset):
        self._run(request, queryset, services.remove_contact, "removed")
