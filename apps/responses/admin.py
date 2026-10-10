from django.contrib import admin

from . import services
from .models import Response

# Read-only for everyone: starting a response consumes a licence and every
# change goes through the service layer, never a form. Two levels of detail:
# a superuser sees everything, including the answers; other staff (support) get a
# debugging view, with which questions are answered by position and no values,
# including the self-report. The answers must not leak through the list columns,
# search or filters either, so none of those touch them.

SUPPORT_FIELDS = (
    "account",
    "survey_version",
    "entitlement",
    "status",
    "pages_completed",
    "answered",
    "started_at",
    "submitted_at",
    "possible_repeat",
)
SUPERUSER_FIELDS = (
    "account",
    "survey_version",
    "entitlement",
    "status",
    "pages_completed",
    "answers",
    "took_before",
    "took_before_via",
    "started_at",
    "submitted_at",
    "possible_repeat",
)


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "survey_version",
        "status",
        "pages_completed",
        "tier",
        "started_at",
        "submitted_at",
        "possible_repeat",
    )
    list_filter = ("status", "possible_repeat")
    search_fields = ("account__email",)
    list_select_related = ("account", "survey_version", "entitlement")

    def get_fields(self, request, obj=None):
        return SUPERUSER_FIELDS if request.user.is_superuser else SUPPORT_FIELDS

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    @admin.display(description="Licence tier")
    def tier(self, response):
        return response.entitlement.tier

    @admin.display(description="Questions answered (positions)")
    def answered(self, response):
        positions = services.answered_positions(response)
        listing = ", ".join(str(p) for p in positions) or "none"
        return f"{len(positions)} of {response.survey_version.question_count}: {listing}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
