"""
The audit log in the staff admin: read-only, and for superusers only.

Each row says who did what to what, and when. People are shown by their
account's number, never a name or an email address; the number links to the
account's own page for a superuser who needs to know who it is.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("at", "who", "action", "target", "facts")
    list_filter = ("action", "at")
    date_hierarchy = "at"
    # Type a number to find everything done to (or by) the thing with that number.
    search_fields = ("=target_id", "=actor__id", "target_type")
    search_help_text = (
        "Search by a number (of the thing acted on, or of the account that acted) "
        'or by a kind of thing, for example "enterprises.invite".'
    )
    list_select_related = ("actor",)
    list_per_page = 100

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    @admin.display(description="Who", ordering="actor")
    def who(self, row):
        if row.actor_id is None:
            return "The site itself, or an account since deleted"
        link = reverse("admin:accounts_account_change", args=[row.actor_id])
        return format_html('<a href="{}">Account #{}</a>', link, row.actor_id)

    @admin.display(description="Done to")
    def target(self, row):
        return f"{row.target_type} #{row.target_id}" if row.target_id else "-"

    @admin.display(description="Details")
    def facts(self, row):
        return ", ".join(f"{key}: {value}" for key, value in row.detail.items()) or "-"

    # Superusers only, whatever permissions a group is given later.
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
