from allauth.account.admin import EmailAddressAdmin as AllauthEmailAddressAdmin
from allauth.account.models import EmailAddress
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.admin.options import ActionLocation
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
    form but not Django's display of the stored password: that shows the
    hashing method, its settings and part of the hash, which nontechnical
    staff read as a fault or a leak. The page says only whether a password is
    set, with a link to set a new one for those who may. New accounts come
    from sign-up or `createsuperuser`, which also create the Person and
    contacts; the admin's own add form would not, so it is switched off.

    Two actions on the list, for superusers, make an account Support staff or
    take that away. Each asks first and leaves a history line on the account.
    """

    list_display = (
        "email",
        "full_name",
        "is_active",
        "is_staff",
        "is_superuser",
        "erased",
        "created_at",
    )
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        ("anonymised_at", admin.EmptyFieldListFilter),
    )
    search_fields = (
        "email",
        "full_name",
        "contact_points__value_normalised",
        "contact_points__value_display",
    )
    ordering = ("email",)
    readonly_fields = (
        "email",
        "person",
        "password_set",
        "created_at",
        "last_login",
        "anonymised_at",
    )
    actions = ["make_support_staff", "remove_support_staff", "look_for_duplicates"]
    inlines = [ReadOnlyContactPoints]

    fieldsets = (
        (None, {"fields": ("email", "full_name", "person", "password_set")}),
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

    @admin.display(description="Password")
    def password_set(self, account):
        """Whether a password is set, in plain words. Never the stored hash or how it is made."""
        if not account.has_usable_password():
            return "No password is set, so nobody can log in to this account with one."
        return "A password is set. Nobody can see it, staff included."

    # --- Support staff ----------------------------------------------------------------

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        actions = super().get_actions(request, action_location)
        if not request.user.is_superuser:
            # Who may enter the admin is for superusers to decide.
            actions.pop("make_support_staff", None)
            actions.pop("remove_support_staff", None)
            # Possible duplicates are for superusers to see, so also to look for.
            actions.pop("look_for_duplicates", None)
        return actions

    @admin.action(description="Look for possible duplicates of the selected accounts")
    def look_for_duplicates(self, request, queryset):
        """
        Queue a look, in the background, for other accounts that may be the
        same person as each selected one. The site does this by itself when
        something changes for an account; this is for accounts that nothing
        has happened to since that was built. It can only bring a pair to
        "Possible duplicates": it never changes an account. No page asks
        first, because there is nothing to undo.
        """
        if not request.user.is_superuser:
            raise PermissionDenied
        # An erased or switched-off account is never part of a pair.
        live = queryset.filter(is_active=True, anonymised_at__isnull=True)
        queued = 0
        for account in live:
            services.look_for_duplicates_later(account)
            # The account's history says who asked for the look.
            self.log_change(request, account, "Looked for possible duplicates")
            queued += 1
        skipped = queryset.count() - queued
        if queued:
            self.message_user(
                request,
                f"Looking for possible duplicates of {queued} account(s) in the background. "
                'Any that are found appear under "Possible duplicates" within a minute.',
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} account(s) were left out: erased or switched off.",
                messages.WARNING,
            )

    @admin.action(description="Make the selected accounts Support staff")
    def make_support_staff(self, request, queryset):
        return self._support_staff(
            request,
            queryset,
            services.make_support_staff,
            action="make_support_staff",
            title="Make these accounts Support staff?",
            button="Yes, make them Support staff",
            history="Made Support staff",
            nothing="was already Support staff",
        )

    @admin.action(description="Take the selected accounts off Support staff")
    def remove_support_staff(self, request, queryset):
        return self._support_staff(
            request,
            queryset,
            services.remove_support_staff,
            action="remove_support_staff",
            title="Take these accounts off Support staff?",
            button="Yes, take them off Support staff",
            history="Taken off Support staff",
            nothing="was not Support staff",
        )

    def _support_staff(self, request, queryset, change, *, action, title, button, history, nothing):
        """
        Both actions: a page that lists who was selected and asks first, then
        the change, one account at a time. An account the service refuses is
        named with the reason and the others carry on.
        """
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.POST.get("confirmed") != "yes":
            context = {
                **self.admin_site.each_context(request),
                "title": title,
                "opts": self.model._meta,
                "accounts": queryset.order_by("email"),
                "action": action,
                "button": button,
                "making": action == "make_support_staff",
            }
            return TemplateResponse(
                request, "admin/accounts/account/support_staff_confirm.html", context
            )
        changed = 0
        for account in queryset:
            try:
                did = change(account)
            except ValidationError as error:
                text = " ".join(error.messages)
                self.message_user(request, f"Account #{account.pk}: {text}", messages.ERROR)
                continue
            if did:
                # The account's history says who let them in, or took that away.
                self.log_change(request, account, history)
                changed += 1
            else:
                self.message_user(request, f"Account #{account.pk} {nothing}.", messages.WARNING)
        if changed:
            self.message_user(request, f"{history}: {changed} account(s).", messages.SUCCESS)
        return None

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and obj.anonymised_at is not None:
            # Nothing on an erased account can be switched back on.
            fields = (
                *fields,
                "full_name",
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
            # Django's own page for setting a password, which asks for it twice.
            extra_context["password_url"] = reverse(
                "admin:auth_user_password_change", args=[object_id]
            )
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


# allauth keeps its own table of emails (login and verification links). It is
# the other half of every contact point, so editing it here would leave our
# table behind, exactly what the comment at the top of this file avoids. Its
# page stays for superusers to look at, read-only. The one action kept is
# allauth's "mark verified", because it fires allauth's email_confirmed signal
# and our receiver marks the contact point verified at the same time; while SES
# is sandboxed it is the only way to verify an address that cannot get mail.
admin.site.unregister(EmailAddress)


@admin.register(EmailAddress)
class ReadOnlyEmailAddressAdmin(AllauthEmailAddressAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
