from django.contrib import admin
from django.db.models import Count

from .models import FunnelEvent

# The steps of the funnel, in order. "Licence upgraded" and "finished a page" are
# shown separately because they are not a step everyone passes through.
STEPS = [
    FunnelEvent.Kind.SIGNED_UP,
    FunnelEvent.Kind.EMAIL_VERIFIED,
    FunnelEvent.Kind.LICENCE_GRANTED,
    FunnelEvent.Kind.SURVEY_STARTED,
    FunnelEvent.Kind.SURVEY_SUBMITTED,
]


def _percent(part, whole):
    return None if not whole else round(100 * part / whole)


def funnel_rows(queryset):
    """Each step with its count and its share of the step before and of sign-ups."""
    counts = dict(queryset.order_by().values_list("kind").annotate(n=Count("id")))
    rows, previous, first = [], None, None
    for kind in STEPS:
        count = counts.get(kind, 0)
        first = count if first is None else first
        rows.append(
            {
                "label": kind.label,
                "count": count,
                "of_previous": None if previous is None else _percent(count, previous),
                "of_signups": None if kind == STEPS[0] else _percent(count, first),
            }
        )
        previous = count
    return rows, counts


def page_rows(queryset):
    pages = (
        queryset.filter(kind=FunnelEvent.Kind.PAGE_LOCKED)
        .order_by("page")
        .values_list("page")
        .annotate(n=Count("id"))
    )
    return [{"page": page, "count": n} for page, n in pages]


@admin.register(FunnelEvent)
class FunnelEventAdmin(admin.ModelAdmin):
    """
    Read-only: an event is a record of something that happened, so nobody adds or
    edits one by hand. Only a superuser can delete (the standard delete action),
    to clear out test sign-ups before launch. The summary above the list follows
    the filters, so a country or a date range gives that funnel.
    """

    list_display = ("occurred_at", "kind", "country", "channel", "tier", "source", "page")
    list_filter = (("occurred_at", admin.DateFieldListFilter), "country", "channel")
    change_list_template = "admin/funnel/funnelevent/change_list.html"

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        context = getattr(response, "context_data", None)
        if context and "cl" in context:
            rows, counts = funnel_rows(context["cl"].queryset)
            context["funnel_rows"] = rows
            context["upgraded"] = counts.get(FunnelEvent.Kind.LICENCE_UPGRADED, 0)
            context["page_rows"] = page_rows(context["cl"].queryset)
        return response

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
