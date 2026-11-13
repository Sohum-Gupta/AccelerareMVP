"""
Milestone 6, PR 1: an organization's surveys as a spreadsheet file.

POST /organizations/<slug>/responses/export/ sends its admin a CSV file: one
row for each submitted survey taken for the organization, with the six things
the responses table shows (the founder's choice of 2026-11-13) and nothing
else. Every download is written to the audit log.

That the file holds only the admin's own organization, never a survey taken
personally and never an answer, is in tests/test_tenant_isolation.py
(TestTheResponsesPages and the lists at its top).
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import csv
import io

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.accounts.models import Account
from apps.audit.models import AuditLog
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.responses import exports
from apps.responses.models import Response

from .orgs import new_member
from .test_response_context import acme, grant  # noqa: F401
from .test_responses_table import admin, member, started, submitted, three  # noqa: F401

TABLE = "/organizations/acme/responses/"
EXPORT = TABLE + "export/"
COLUMNS = ["name", "email", "started", "submitted", "results_level", "possible_repeat"]
BUTTON = "Download as a spreadsheet (CSV)"


def download(client, address=EXPORT):
    """Press the button. Returns the response and the whole file as text."""
    answer = client.post(address)
    assert answer.status_code == 200, answer.status_code
    return answer, b"".join(answer.streaming_content).decode("utf-8")


def rows(client):
    """The file as a spreadsheet reads it: (the header, the other lines)."""
    _answer, text = download(client)
    lines = list(csv.reader(io.StringIO(text.removeprefix(exports.BYTE_ORDER_MARK))))
    return lines[0], lines[1:]


def day(days_ago):
    return (timezone.now() - timezone.timedelta(days=days_ago)).date().isoformat()


def named(acme, name, email="someone@example.com"):
    """A member of Acme with a licence and exactly this name, whatever is in it."""
    membership = new_member(acme[0], email)
    accounts.set_full_name(membership.account, name)
    grant(membership, 2)
    return membership


def exported():
    return AuditLog.objects.filter(action="responses.exported")


@pytest.mark.django_db
class TestTheFile:
    def test_it_is_a_csv_file_named_for_the_organization_and_the_day(self, client, admin, three):
        answer, text = download(client)
        assert answer["Content-Type"] == "text/csv; charset=utf-8"
        today = timezone.localdate().isoformat()
        assert answer["Content-Disposition"] == f'attachment; filename="responses-acme-{today}.csv"'
        assert "no-store" in answer["Cache-Control"]
        # The mark that tells Excel the file is UTF-8.
        assert text.startswith("﻿")

    def test_it_is_sent_as_it_is_made_not_built_first(self, client, admin, three):
        assert client.post(EXPORT).streaming

    def test_the_header_is_the_six_things_the_table_shows(self, client, admin, three):
        header, _lines = rows(client)
        assert header == COLUMNS

    def test_one_row_for_each_submitted_survey_newest_first(self, client, admin, three):
        """Carol and Alice submitted; Bob is still answering and is not in the file."""
        _header, lines = rows(client)
        assert lines == [
            ["Alice Example", "alice@example.com", day(4), day(2), "Tier 3", "no"],
            ["Carol Example", "carol@example.com", day(5), day(1), "Tier 1", "no"],
        ]

    def test_the_filters_on_the_page_do_not_change_the_file(self, client, admin, three):
        _answer, text = download(client, EXPORT + "?status=draft&tier=1&repeat=yes")
        assert "Alice Example" in text and "Carol Example" in text and "Bob Example" not in text

    def test_a_possible_repeat_and_a_withdrawn_licence(self, client, admin, three):
        Response.objects.filter(pk=three["carol"].pk).update(possible_repeat=True)
        licences.revoke(three["carol"].entitlement)
        _header, lines = rows(client)
        carol = next(line for line in lines if line[0] == "Carol Example")
        assert carol[4:] == ["Free (licence withdrawn)", "yes"]

    def test_an_erased_member_has_no_name_or_address_and_one_who_left_is_still_listed(
        self, client, acme, admin, three
    ):
        name, email = "Alice Example", "alice@example.com"
        erasure.erase_account(three["alice"].account)
        orgs.deactivate_membership(three["carol"].membership, by=admin)
        _answer, text = download(client)
        _header, lines = rows(client)
        assert [line[:2] for line in lines] == [
            ["Erased member", ""],
            ["Carol Example", "carol@example.com"],
        ]
        assert name not in text and email not in text

    def test_someone_with_no_name_has_an_empty_cell(self, client, acme, admin):
        nameless = member(acme, "Dana Example")
        # An account made before sign-up asked for a name.
        Account.objects.filter(pk=nameless.account_id).update(full_name="")
        submitted(nameless)
        _header, lines = rows(client)
        assert lines[0][:2] == ["", "dana@example.com"]

    def test_a_name_with_an_accent_or_a_comma_survives(self, client, acme, admin):
        submitted(named(acme, "Zoë O'Brien, Jr."))
        _header, lines = rows(client)
        assert lines[0][0] == "Zoë O'Brien, Jr."

    def test_with_no_submitted_survey_the_file_is_only_its_header(self, client, acme, admin):
        started(member(acme, "Bob Example"))
        header, lines = rows(client)
        assert header == COLUMNS and lines == []


@pytest.mark.django_db
class TestACellIsNeverAFormula:
    @pytest.mark.parametrize("sign", ["=", "+", "-", "@"])
    def test_a_name_that_starts_like_a_formula_is_written_as_text(self, client, acme, admin, sign):
        submitted(named(acme, f"{sign}SUM(1) Example"))
        _header, lines = rows(client)
        assert lines[0][0] == f"'{sign}SUM(1) Example"

    @pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t=", "\r=", "\n="])
    def test_the_guard(self, start):
        assert exports.safe(f"{start}1+1") == f"'{start}1+1"

    def test_the_guard_leaves_ordinary_text_alone(self):
        assert exports.safe("Alice Example") == "Alice Example"
        assert exports.safe("a=b") == "a=b"
        assert exports.safe("2026-11-13") == "2026-11-13"
        assert exports.safe(None) == ""
        assert exports.safe(7) == "7"

    def test_every_cell_goes_through_the_guard(self):
        lines = list(exports.lines(["a", "b"], [("=1", "ok"), ("fine", "@x")]))
        assert lines[1:] == ["'=1,ok\r\n", "fine,'@x\r\n"]


@pytest.mark.django_db
class TestEachDownloadIsRecorded:
    def test_who_which_organization_and_how_many_rows(self, client, acme, admin, three):
        download(client)
        row = exported().get()
        assert row.actor_id == admin.account_id
        assert (row.target_type, row.target_id) == ("enterprises.enterprise", str(acme[0].pk))
        assert row.detail == {"rows": 2, "answers": False, "organization": acme[0].pk}

    def test_the_record_holds_no_name_or_address(self, client, acme, admin, three):
        download(client)
        stored = str(exported().values().get())
        for word in ("Alice", "Carol", "Example", "@", "Acme", "acme"):
            assert word not in stored, word

    def test_each_press_is_its_own_row(self, client, admin, three):
        download(client)
        download(client)
        assert exported().count() == 2

    def test_opening_the_address_makes_no_file_and_no_record(self, client, admin, three):
        """Only the button (a POST) downloads: a link, a reload or a crawler cannot."""
        assert client.get(EXPORT).status_code == 405
        assert not exported().exists()

    def test_the_record_is_written_before_the_first_line_is_sent(self, client, admin, three):
        """So a download that fails halfway is still on record."""
        answer = client.post(EXPORT)
        assert exported().count() == 1  # nothing of the file has been read yet
        answer.close()


@pytest.mark.django_db
class TestTheButton:
    def page(self, client, query=""):
        return client.get(TABLE + query).content.decode()

    def test_it_is_on_the_responses_page_and_posts_to_the_export(self, client, admin, three):
        text = self.page(client)
        assert BUTTON in text
        assert f'<form method="post" action="{EXPORT}"' in text
        assert "It never holds anyone's answers" in text and "Each download is recorded" in text

    def test_the_form_carries_the_sites_security_token(self, admin, three):
        """Without it another website could make an admin's browser press the button."""
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(admin.account)
        assert strict.post(EXPORT).status_code == 403
        assert not exported().exists()
        form = strict.get(TABLE).content.decode().split(f'action="{EXPORT}"')[1].split("</form>")[0]
        token = form.split('name="csrfmiddlewaretoken" value="')[1].split('"')[0]
        assert strict.post(EXPORT, {"csrfmiddlewaretoken": token}).status_code == 200

    def test_it_stays_when_the_filters_match_nothing(self, client, admin, three):
        text = self.page(client, "?repeat=yes")
        assert "No response matches these filters." in text and BUTTON in text

    def test_there_is_none_until_a_survey_is_submitted(self, client, acme, admin):
        assert BUTTON not in self.page(client)
        started(member(acme, "Bob Example"))
        assert BUTTON not in self.page(client)
        submitted(member(acme, "Carol Example"))
        assert BUTTON in self.page(client)
