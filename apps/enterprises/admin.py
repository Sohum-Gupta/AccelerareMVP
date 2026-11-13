from django.contrib import admin

from .models import Enterprise, Invite, JoinCode, Membership

# Read-only for now. Every change to an organization goes through services.py
# (Milestone 3, PR 3 onwards), so there is nothing here to add, edit or delete.
# PR 12 adds the staff tools: the people limit, creating an organization for a
# customer, and actions that call the services.
#
# An invite's link token and a join code are never listed: the list pages are
# for finding a row, not for handing out a way in.


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Enterprise)
class EnterpriseAdmin(ReadOnlyAdmin):
    list_display = ("name", "slug", "people_limit", "created_at")
    search_fields = ("name", "slug")


@admin.register(Membership)
class MembershipAdmin(ReadOnlyAdmin):
    list_display = ("id", "account", "enterprise", "role", "status", "joined_at", "deactivated_at")
    list_filter = ("role", "status")
    search_fields = ("account__email", "account__full_name", "enterprise__name")
    list_select_related = ("account", "enterprise")


@admin.register(Invite)
class InviteAdmin(ReadOnlyAdmin):
    list_display = ("id", "enterprise", "email", "expires_at", "accepted_at", "revoked_at")
    search_fields = ("email", "enterprise__name")
    list_select_related = ("enterprise",)
    exclude = ("token",)

    def get_readonly_fields(self, request, obj=None):
        return [name for name in super().get_readonly_fields(request, obj) if name != "token"]


@admin.register(JoinCode)
class JoinCodeAdmin(ReadOnlyAdmin):
    list_display = ("id", "enterprise", "uses", "max_uses", "expires_at", "revoked_at")
    search_fields = ("enterprise__name",)
    list_select_related = ("enterprise",)
