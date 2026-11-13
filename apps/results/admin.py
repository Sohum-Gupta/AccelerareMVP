"""
Results in the staff admin: read-only, and for superusers only.

A result is worked out by the algorithm in the background; nobody types one
in. It is as private as the answers it came from, which only superusers see,
so only superusers see this. The table is empty until there is an algorithm.
"""

from django.contrib import admin

from .models import Result


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("__str__", "algorithm_version", "computed_at")
    list_filter = ("algorithm_version",)
    search_fields = ("=response__id",)
    search_help_text = "Search by a response's number."

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def _is_superuser(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return self._is_superuser(request)

    def has_view_permission(self, request, obj=None):
        return self._is_superuser(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
