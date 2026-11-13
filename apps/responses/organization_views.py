"""
What an organization's admins see of the surveys taken for it:
/organizations/<slug>/responses/ (the table),
/organizations/<slug>/responses/<id>/ (one response) and
/organizations/<slug>/responses/export/ (the table's submitted surveys as a
spreadsheet file, Milestone 6).

These pages live here, not with the other organization pages, because the
apps depend on each other one way (accounts <- enterprises <- entitlements <-
responses): this app may use the organization's scoping, and the enterprises
app must never import a response.

What an admin is told about a response (the founder's rule of 2026-11-12, and
the promise the disclosure and join pages make to the member):

* who took it (name and the address admins see, or "Erased member"), whether
  it is in progress or submitted, the dates it was started and submitted, its
  results level and the possible-repeat mark;
* never the answers, the answer to "have you taken this before", or how far an
  unfinished one has got. Results are added in Phase 2.

How that is kept true:

* Both pages start with scoping.for_admin: the slug only says which
  organization is meant, and what comes back is this account's own active
  admin membership, or "not found".
* Every query goes through _taken_for, which keeps to that one organization. A
  response taken personally has no membership, so it can never match; another
  organization's id is "not found", the same answer as an id that does not exist.
* _taken_for also leaves the answers, the self-report and the progress out of
  the query altogether (`defer`), so they are not even read from the database.
* The templates get plain values (_facts), never a Response.
* The file is made from the same query and the same facts, so it can hold
  nothing the table does not show.

tests/test_tenant_isolation.py holds all of this to account.
"""

from django.db.models import F
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import verified_email_required
from apps.enterprises import scoping
from apps.enterprises.shown import member_email, member_name, organization

from . import exports
from .forms import ResponseFilterForm
from .models import Response

# What an admin must never be shown. Not read from the database on these pages.
_NEVER = ("answers", "took_before", "took_before_via", "match_hint", "pages_completed")

# The orders the table offers, by the value in the address.
_ORDERS = {
    "-started": ("-started_at", "-id"),
    "started": ("started_at", "id"),
    # Unfinished ones have no submit date: they go last.
    "-submitted": (F("submitted_at").desc(nulls_last=True), "-id"),
}

# The columns of the file: the six things the table shows (the founder's choice
# of 2026-11-13). Adding one is a product decision, not a code change.
EXPORT_COLUMNS = ("name", "email", "started", "submitted", "results_level", "possible_repeat")


def _taken_for(enterprise):
    """Every response taken for this organization, and only what an admin may know of each."""
    return (
        Response.objects.filter(membership__enterprise=enterprise)
        .select_related("entitlement", "membership__account", "membership__joined_via_invite")
        .defer(*_NEVER)
    )


def _facts(response):
    """What an admin is told about one response. Plain values only."""
    member = response.membership
    withdrawn = response.entitlement.revoked_at is not None
    return {
        "id": response.pk,
        "name": member_name(member.account),
        "email": member_email(member),
        "erased": member.account.anonymised_at is not None,
        "member_active": member.is_active,
        "submitted": response.status == Response.Status.SUBMITTED,
        "started_at": response.started_at,
        "submitted_at": response.submitted_at,
        # As on the person's own pages: a withdrawn licence has no results level.
        "tier": 0 if withdrawn else response.entitlement.tier,
        "withdrawn": withdrawn,
        "possible_repeat": response.possible_repeat,
    }


def _by_member(row):
    """Alphabetical by name; people with no name, then erased members, at the end."""
    return (row["erased"], not row["name"], row["name"].casefold(), row["id"])


@never_cache
@require_GET
@verified_email_required
def table(request, slug):
    """
    The surveys taken for the admin's organization, newest first, with filters
    (status, results level, possible repeats) and a choice of order. A filter
    value the page does not offer is ignored.
    """
    membership = scoping.for_admin(request, slug)
    everything = _taken_for(membership.enterprise)
    form = ResponseFilterForm(request.GET or None)
    chosen = form.cleaned_data if form.is_bound and form.is_valid() else {}

    responses = everything
    if chosen.get("status"):
        responses = responses.filter(status=chosen["status"])
    if chosen.get("tier"):
        responses = responses.filter(
            entitlement__tier=int(chosen["tier"]), entitlement__revoked_at__isnull=True
        )
    if chosen.get("repeat"):
        responses = responses.filter(possible_repeat=True)
    order = chosen.get("sort") or "-started"
    rows = [
        _facts(response)
        for response in responses.order_by(*_ORDERS.get(order, _ORDERS["-started"]))
    ]
    if order == "member":
        rows.sort(key=_by_member)

    context = {
        "organization": organization(membership),
        "form": form,
        "rows": rows,
        "total": everything.count(),
        # The file holds submitted surveys only; with none there is no button.
        "can_export": _submitted_for(membership.enterprise).exists(),
        "filtered": any(chosen.get(name) for name in ("status", "tier", "repeat")),
    }
    return render(request, "responses/organization_table.html", context)


@never_cache
@require_GET
@verified_email_required
def detail(request, slug, pk):
    """One response taken for the admin's organization. Any other id is "not found"."""
    membership = scoping.for_admin(request, slug)
    response = get_object_or_404(_taken_for(membership.enterprise), pk=pk)
    context = {"organization": organization(membership), "row": _facts(response)}
    return render(request, "responses/organization_response.html", context)


def _submitted_for(enterprise):
    """The submitted surveys taken for this organization, newest first, as the table lists them."""
    return (
        _taken_for(enterprise)
        .filter(status=Response.Status.SUBMITTED)
        .order_by(*_ORDERS["-started"])
    )


def _level_words():
    """How each results level is named, taken from the one template that names them."""
    return {
        tier: render_to_string("responses/_tier.html", {"tier": tier}).strip() for tier in range(4)
    }


def _export_rows(responses):
    """One line of the file for each response: the table's facts, as plain text."""
    words = _level_words()
    for response in responses.iterator():
        row = _facts(response)
        level = words[row["tier"]]
        yield (
            row["name"],
            row["email"],
            exports.day(row["started_at"]),
            exports.day(row["submitted_at"]),
            f"{level} (licence withdrawn)" if row["withdrawn"] else level,
            "yes" if row["possible_repeat"] else "no",
        )


@never_cache
@require_POST
@verified_email_required
def export(request, slug):
    """
    The organization's submitted surveys as a spreadsheet file: every one of
    them, whatever filter the table has on, with the six columns the table
    shows and nothing else. A POST, so that only a deliberate press of the
    button makes a file, and the download is noted in the audit log first.
    """
    membership = scoping.for_admin(request, slug)
    enterprise = membership.enterprise
    responses = _submitted_for(enterprise)
    exports.record(
        membership.account_id, rows=responses.count(), answers=False, organization=enterprise
    )
    filename = f"responses-{enterprise.slug}-{timezone.localdate().isoformat()}.csv"
    return exports.download(filename, EXPORT_COLUMNS, _export_rows(responses))
