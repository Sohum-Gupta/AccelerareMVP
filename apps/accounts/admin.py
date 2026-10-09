from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError

from . import services
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


@admin.register(Account)
class AccountAdmin(UserAdmin):
    """
    Django's stock UserAdmin assumes a username field, so the fieldsets and
    search/ordering are redefined around email. It keeps the password-change
    form and the hashed-password display. New accounts come from sign-up or
    `createsuperuser`, which also create the Person and contacts; the admin's
    own add form would not, so it is switched off.
    """

    list_display = ("email", "is_active", "is_staff", "is_superuser", "created_at")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = (
        "email",
        "contact_points__value_normalised",
        "contact_points__value_display",
    )
    ordering = ("email",)
    readonly_fields = ("email", "person", "created_at", "last_login")
    inlines = [ReadOnlyContactPoints]

    fieldsets = (
        (None, {"fields": ("email", "person", "password")}),
        ("Status", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
        ("Dates", {"fields": ("created_at", "last_login")}),
    )

    def has_add_permission(self, request):
        return False


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
