from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from apps.accounts.admin_links import link

from . import exports, services
from .models import Response

# Read-only for everyone: starting a response consumes a licence and every
# change goes through the service layer, never a form. Two levels of detail:
# a superuser sees everything, including the answers; other staff (support) get a
# debugging view, with which questions are answered by position and no values,
# including the self-report. The answers must not leak through the list columns,
# search or filters either, so none of those touch them. "Taken for" says whether
# an attempt is personal or for an organization (and which).
#
# Two downloads (Milestone 6), each behind a page that says what the file holds:
# every submitted survey as a CSV file with the answers, for superusers; and the
# same without the answers, for anyone who may look at responses here. Neither
# file holds a name or an email address. Each download goes in the audit log.

SUPPORT_FIELDS = (
    "account",
    "context",
    "membership",
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
    "context",
    "membership",
    "survey_version",
    "entitlement",
    "status",
    "pages_completed",
    "answers",
    "took_before",
    "took_before_via",
    "match_hint",
    "started_at",
    "submitted_at",
    "possible_repeat",
)


class TakenForFilter(admin.SimpleListFilter):
    """Personal surveys, or those taken for an organization."""

    title = "taken for"
    parameter_name = "taken_for"

    def lookups(self, request, model_admin):
        return [("personal", "The person themselves"), ("organization", "An organization")]

    def queryset(self, request, queryset):
        if self.value() == "personal":
            return queryset.filter(membership__isnull=True)
        if self.value() == "organization":
            return queryset.filter(membership__isnull=False)
        return queryset


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account_link",
        "context",
        "survey_version",
        "status",
        "pages_completed",
        "tier",
        "started_at",
        "submitted_at",
        "possible_repeat",
    )
    # The date filter's "Past 7 days" is what the number on the admin's first page links to.
    list_filter = (
        "status",
        TakenForFilter,
        "possible_repeat",
        ("submitted_at", admin.DateFieldListFilter),
    )
    # Who took it (email, name or account number), which organization, or its own
    # number. Never the answers: the search must not be a way to probe them.
    search_fields = (
        "account__email",
        "account__full_name",
        "=account__id",
        "membership__enterprise__name",
        "=id",
    )
    search_help_text = (
        "Search by the email, name or account number of who took it, by an organization's "
        "name, or by the response's own number."
    )
    list_select_related = ("account", "survey_version", "entitlement", "membership__enterprise")

    def get_fields(self, request, obj=None):
        return SUPERUSER_FIELDS if request.user.is_superuser else SUPPORT_FIELDS

    # --- the two downloads ------------------------------------------------------------

    def get_urls(self):
        custom = [
            path(
                "export/",
                self.admin_site.admin_view(self.export_view),
                name="responses_response_export",
            ),
            path(
                "export/answers/",
                self.admin_site.admin_view(self.export_answers_view),
                name="responses_response_export_answers",
            ),
        ]
        return [*custom, *super().get_urls()]

    def changelist_view(self, request, extra_context=None):
        extra_context = {
            **(extra_context or {}),
            "export_url": reverse("admin:responses_response_export"),
            # Only a superuser may read answers, here or in a file.
            "export_answers_url": (
                reverse("admin:responses_response_export_answers")
                if request.user.is_superuser
                else None
            ),
        }
        return super().changelist_view(request, extra_context)

    def export_view(self, request):
        """Every submitted survey without the answers, for whoever may look at responses."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        return self._export(request, answers=False)

    def export_answers_view(self, request):
        """The same with the answers. Superusers only, like the answers on a response's page."""
        if not request.user.is_superuser:
            raise PermissionDenied
        return self._export(request, answers=True)

    def _export(self, request, *, answers):
        """The page that says what the file holds; its button (a POST) records and sends it."""
        responses = exports.submitted_surveys(answers=answers)
        count = responses.count()
        if request.method == "POST":
            exports.record(request.user, rows=count, answers=answers)
            kind = "with-answers" if answers else "without-answers"
            filename = f"surveys-{kind}-{timezone.localdate().isoformat()}.csv"
            return exports.download(
                filename,
                exports.staff_header(answers=answers),
                exports.staff_rows(responses, answers=answers),
            )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Download every submitted survey, {'with' if answers else 'without'} answers",
            "opts": self.model._meta,
            "answers": answers,
            "count": count,
            "columns": exports.staff_header(answers=answers),
        }
        return TemplateResponse(request, "admin/responses/response/export.html", context)

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    @admin.display(description="Account", ordering="account__email")
    def account_link(self, response):
        return link(response.account)

    @admin.display(description="Taken for")
    def context(self, response):
        """Who the attempt was taken for: the person themselves, or an organization (a link)."""
        if response.membership_id is None:
            return "Personal"
        return link(response.membership.enterprise)

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
