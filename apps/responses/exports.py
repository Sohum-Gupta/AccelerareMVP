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

The rows themselves are built by whoever knows what may be in them: the
organization's file by organization_views.py, from the same facts as its page.

This lives in the responses app, not an app of its own, because an export
reads responses and this app must stay the last one (tests/test_app_dependencies.py).
"""

import csv

from django.http import StreamingHttpResponse

from apps.audit import services as audit

# Tells Excel the file is UTF-8, so a name with an accent reads correctly.
BYTE_ORDER_MARK = "﻿"

# What a spreadsheet takes as the start of a formula. A tab or a line break in
# front of one of the four signs would otherwise slip past, so they count too.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe(value):
    """The cell as text that no spreadsheet will run as a formula."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


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
