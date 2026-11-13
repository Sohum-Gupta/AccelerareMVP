"""
Surveys as a spreadsheet file (CSV): what every download has in common.

A download is the one place data leaves the site. A page can be changed
tomorrow; a file on somebody's laptop cannot. So three things are done here,
once, for every file the site makes:

* Every cell is guarded (`safe`). A CSV file is plain text, but a spreadsheet
  treats a cell that begins with =, +, - or @ as a formula and runs it. A
  person types their own name and an admin their organization's, so either
  could be a formula that runs on the computer of whoever opens the file. An
  apostrophe in front makes the spreadsheet show it as text.
* The file is sent line by line as it is read from the database (`download`),
  so a large one never sits in memory.
* The download is written to the audit log (`record`): who took it, which
  organization or the whole site, and how many rows. Never a name.

The rows themselves are built by whoever knows what may be in them. The
organization's file is made by organization_views.py, from the same facts as
its page. The two staff files, downloaded from the Django admin, are made
here (`staff_header`, `staff_rows`): every submitted survey on the site, with
each person shown as an account number and never a name or an email address
(the founder's choice of 2026-11-13). One has the answers and is for
superusers; the other has none and is for anyone who may look at responses in
the admin, Support staff included.

This lives in the responses app, not an app of its own, because an export
reads responses and this app must stay the last one (tests/test_app_dependencies.py).
"""

import csv

from django.http import StreamingHttpResponse
from django.utils import timezone

from apps.audit import services as audit
from apps.survey.models import Question

from .models import Response

# Tells Excel the file is UTF-8, so a name with an accent reads correctly.
BYTE_ORDER_MARK = "﻿"

# What a spreadsheet takes as the start of a formula. A tab or a line break in
# front of one of the four signs would otherwise slip past, so they count too.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe(value):
    """The cell as text that no spreadsheet will run as a formula."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


def day(moment):
    """The day only, as 2026-11-13, so a spreadsheet sorts it. The pages show the day too."""
    return timezone.localtime(moment).date().isoformat()


class _Line:
    """What csv.writer writes to: it hands each finished line straight back."""

    def write(self, line):
        return line


def lines(header, rows):
    """The file, one line at a time: the mark, the header, then each row, guarded."""
    writer = csv.writer(_Line())
    yield BYTE_ORDER_MARK + writer.writerow(header)
    for row in rows:
        yield writer.writerow([safe(cell) for cell in row])


def download(filename, header, rows):
    """A response that sends the file as it is made. `rows` may be a generator."""
    response = StreamingHttpResponse(lines(header, rows), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


def record(actor, *, rows, answers, organization=None):
    """
    Note in the audit log that `actor` started a download of `rows` surveys.
    `organization` is the organization whose surveys they are, or None for the
    whole site; `answers` says whether the answers were in the file. Call it
    before the first line is sent: a download that then fails halfway is still
    on record, and there is never a file without one.
    """
    detail = {"rows": rows, "answers": answers}
    if organization is not None:
        detail["organization"] = organization.pk
    return audit.record(actor, "responses.exported", organization, **detail)


# --- the staff files --------------------------------------------------------------

# What both staff files hold. No name and no email address: a person is a number.
STAFF_COLUMNS = (
    "response",
    "account",
    "survey_version",
    "organization_number",
    "organization",
    "tier",
    "started",
    "submitted",
    "possible_repeat",
)
# What only the file with answers adds, before q1, q2 and so on.
ANSWER_COLUMNS = ("took_before", "took_before_via")
# What a file without answers must not even read from the database.
_ANSWERS = ("answers", "took_before", "took_before_via")


def submitted_surveys(*, answers):
    """
    Every submitted survey on the site, oldest first, for a staff file. The
    box under "Yes" is never read, and without `answers` neither are the
    answers nor the answer to "have you taken this before".
    """
    never = ("match_hint", "pages_completed") + (() if answers else _ANSWERS)
    return (
        Response.objects.filter(status=Response.Status.SUBMITTED)
        .select_related("entitlement", "membership__enterprise", "survey_version")
        .defer(*never)
        .order_by("id")
    )


def _positions():
    """For each survey version, where each of its statements stands: {version: {"<id>": position}}."""
    found = {}
    for version, question, position in Question.objects.values_list(
        "survey_version_id", "id", "position"
    ):
        found.setdefault(version, {})[str(question)] = position
    return found


def _width(positions):
    """How many q columns the file needs: as many as the longest survey version has."""
    return max((max(places.values()) for places in positions.values()), default=0)


def staff_header(*, answers):
    """The first line of a staff file. The statements are q1, q2, ... by position, never their text."""
    if not answers:
        return STAFF_COLUMNS
    questions = tuple(f"q{number}" for number in range(1, _width(_positions()) + 1))
    return STAFF_COLUMNS + ANSWER_COLUMNS + questions


def _yes_no(value):
    return "yes" if value else "no"


def staff_rows(responses, *, answers):
    """One line for each response: who by number, for which organization, when, and its tier."""
    positions = _positions() if answers else {}
    width = _width(positions)
    for response in responses.iterator():
        enterprise = response.membership.enterprise if response.membership_id else None
        licence = response.entitlement
        row = [
            response.pk,
            response.account_id,
            response.survey_version.number,
            enterprise.pk if enterprise else "",
            enterprise.name if enterprise else "",
            # As the pages show it: a withdrawn licence has no results level.
            0 if licence.revoked_at is not None else licence.tier,
            day(response.started_at),
            day(response.submitted_at),
            _yes_no(response.possible_repeat),
        ]
        if answers:
            row += [_yes_no(response.took_before), response.took_before_via]
            cells = [""] * width
            places = positions.get(response.survey_version_id, {})
            for question, value in response.answers.items():
                if question in places:
                    cells[places[question] - 1] = value
            row += cells
        yield row
