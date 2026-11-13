"""
Milestone 6, PR 2: every submitted survey as a spreadsheet file, for staff.

Two downloads on the "Responses" page of the Django admin, each behind a page
that says what the file holds (the founder's choices of 2026-11-13):

* with the answers, for superusers only;
* without the answers, for anyone who may look at responses there, which is
  Support staff too.

In both, a person is an account number: no name and no email address. Each
download is written to the audit log.

The world: Ann took the survey personally (tier 1) and said she had taken it
before; Bob took it for Acme (tier 2); Cy has started it personally and not
finished.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import csv
import io

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.accounts.models import Account
from apps.audit.models import AuditLog
from apps.enterprises.models import Enterprise
from apps.entitlements import services as licences
from apps.responses import exports
from apps.responses import services as surveys
from apps.responses.models import Response
from apps.survey.models import Question, SurveyVersion

from .orgs import new_member, org_with_admin
from .test_matching import give, take
from .test_profile import verified_account
from .test_response_context import finish, grant
from .test_support_staff_admin import root, support  # noqa: F401

LIST = reverse("admin:responses_response_changelist")
PLAIN = reverse("admin:responses_response_export")
ANSWERS = reverse("admin:responses_response_export_answers")
BASE = [
    "response",
    "account",
    "survey_version",
    "organization_number",
    "organization",
    "tier",
    "started",
    "submitted",
    "possible_repeat",
]


def named(email, name):
    account = verified_account(email)
    accounts.set_full_name(account, name)
    return account


@pytest.fixture
def world(db):
    """Ann (personal, said yes), Bob (for Acme), Cy (unfinished). Returns what the tests need."""
    ann = named("ann@example.com", "Ann Example")
    give(ann, 1)
    ann_response = take(ann, took_before=True)

    enterprise, admin = org_with_admin("Acme")
    bob = new_member(enterprise, "bob@example.com")
    accounts.set_full_name(bob.account, "Bob Example")
    grant(bob, 2)
    bob_response = take(bob.account, bob)

    cy = named("cy@example.com", "Cy Example")
    give(cy, 3)
    surveys.start_response(cy)

    return {
        "ann": ann_response,
        "bob": bob_response,
        "enterprise": enterprise,
        "people": [ann, bob.account, cy, admin.account],
    }


def numbered_answers(response):
    """Give the response a different answer at each position, so a column out of place shows."""
    questions = Question.objects.filter(survey_version=response.survey_version)
    answers = {str(question.pk): question.position % 4 + 1 for question in questions}
    Response.objects.filter(pk=response.pk).update(answers=answers)
    return [str(position % 4 + 1) for position in range(1, questions.count() + 1)]


def download(client, address):
    answer = client.post(address)
    assert answer.status_code == 200, answer.status_code
    return answer, b"".join(answer.streaming_content).decode("utf-8")


def rows(client, address):
    """The file as a spreadsheet reads it: (the header, {response number: its line as a dict})."""
    _answer, text = download(client, address)
    lines = list(csv.reader(io.StringIO(text.removeprefix(exports.BYTE_ORDER_MARK))))
    header = lines[0]
    return header, {int(line[0]): dict(zip(header, line, strict=True)) for line in lines[1:]}


def exported():
    return AuditLog.objects.filter(action="responses.exported")


def today():
    return timezone.localdate().isoformat()


@pytest.mark.django_db
class TestTheFileWithoutAnswers:
    def test_its_columns_hold_no_answer_and_nobodys_name(self, client, root, world):
        header, _lines = rows(client, PLAIN)
        assert header == BASE

    def test_one_row_for_each_submitted_survey_and_none_for_an_unfinished_one(
        self, client, root, world
    ):
        _header, lines = rows(client, PLAIN)
        assert set(lines) == {world["ann"].pk, world["bob"].pk}

    def test_a_personal_survey_and_one_taken_for_an_organization(self, client, root, world):
        _header, lines = rows(client, PLAIN)
        ann, bob = world["ann"], world["bob"]
        version = str(ann.survey_version.number)
        assert lines[ann.pk] == {
            "response": str(ann.pk),
            "account": str(ann.account_id),
            "survey_version": version,
            "organization_number": "",
            "organization": "",
            "tier": "1",
            "started": today(),
            "submitted": today(),
            "possible_repeat": "yes",  # she said she had taken it before
        }
        assert lines[bob.pk] == {
            "response": str(bob.pk),
            "account": str(bob.account_id),
            "survey_version": version,
            "organization_number": str(world["enterprise"].pk),
            "organization": "Acme",
            "tier": "2",
            "started": today(),
            "submitted": today(),
            "possible_repeat": "no",
        }

    def test_the_rows_are_in_the_order_the_surveys_were_started(self, client, root, world):
        """Oldest first, so a later download is the earlier one with new rows at the end."""
        cy = Account.objects.get(email="cy@example.com")
        finish(cy.responses.get())
        Response.objects.filter(pk=world["ann"].pk).update(started_at=timezone.now())
        _header, lines = rows(client, PLAIN)
        assert list(lines) == sorted(lines) and len(lines) == 3

    def test_a_withdrawn_licence_is_tier_0(self, client, root, world):
        licences.revoke(world["bob"].entitlement)
        _header, lines = rows(client, PLAIN)
        assert lines[world["bob"].pk]["tier"] == "0"

    def test_it_is_a_csv_file_named_for_what_it_is_and_the_day(self, client, root, world):
        answer, text = download(client, PLAIN)
        assert answer.streaming
        assert answer["Content-Type"] == "text/csv; charset=utf-8"
        assert answer["Content-Disposition"] == (
            f'attachment; filename="surveys-without-answers-{today()}.csv"'
        )
        assert text.startswith("﻿")

    def test_the_answers_are_not_even_read_from_the_database(self, client, root, world):
        with CaptureQueriesContext(connection) as queries:
            download(client, PLAIN)
        about_responses = [q["sql"] for q in queries if "responses_response" in q["sql"]]
        assert about_responses
        for sql in about_responses:
            for column in ("answers", "took_before", "took_before_via", "match_hint"):
                assert f'"{column}"' not in sql, f"the file reads {column}"


@pytest.mark.django_db
class TestTheFileWithAnswers:
    def test_its_columns_are_the_same_then_the_self_report_then_each_statement_by_position(
        self, client, root, world
    ):
        header, _lines = rows(client, ANSWERS)
        count = world["ann"].survey_version.questions.count()
        assert count >= 5
        assert header == [
            *BASE,
            "took_before",
            "took_before_via",
            *[f"q{n}" for n in range(1, count + 1)],
        ]

    def test_each_answer_is_under_the_position_of_its_statement(self, client, root, world):
        expected = numbered_answers(world["bob"])
        header, lines = rows(client, ANSWERS)
        bob = lines[world["bob"].pk]
        assert [bob[column] for column in header if column.startswith("q")] == expected
        # The other columns are the same as in the file without answers.
        assert bob["account"] == str(world["bob"].account_id) and bob["organization"] == "Acme"

    def test_the_statements_are_numbered_by_position_not_by_database_number(
        self, client, root, world
    ):
        """Swap the first and last statements' positions: their answers swap columns."""
        expected = numbered_answers(world["bob"])
        questions = list(Question.objects.filter(survey_version=world["bob"].survey_version))
        first, last = questions[0], questions[-1]
        Question.objects.filter(pk=first.pk).update(position=9999)
        Question.objects.filter(pk=last.pk).update(position=first.position)
        Question.objects.filter(pk=first.pk).update(position=last.position)
        _header, lines = rows(client, ANSWERS)
        bob = lines[world["bob"].pk]
        assert bob["q1"] == expected[-1] and bob[f"q{len(questions)}"] == expected[0]

    def test_the_answer_to_have_you_taken_this_before(self, client, root, world):
        _header, lines = rows(client, ANSWERS)
        ann, bob = lines[world["ann"].pk], lines[world["bob"].pk]
        assert (ann["took_before"], ann["took_before_via"]) == ("yes", "other")
        assert (bob["took_before"], bob["took_before_via"]) == ("no", "")

    def test_the_header_never_holds_a_statements_wording(self, client, root, world):
        _answer, text = download(client, ANSWERS)
        for wording in Question.objects.values_list("text", flat=True):
            assert wording not in text

    def test_a_longer_survey_version_widens_the_header(self, client, root, world):
        longer = SurveyVersion.objects.create(
            number=99, published_at=timezone.now(), question_count=1
        )
        Question.objects.create(survey_version=longer, position=40, text="A placeholder.")
        header, lines = rows(client, ANSWERS)
        assert header[-1] == "q40"
        assert lines[world["bob"].pk]["q40"] == ""

    def test_the_box_under_yes_is_never_read(self, client, root, world):
        with CaptureQueriesContext(connection) as queries:
            download(client, ANSWERS)
        about_responses = [q["sql"] for q in queries if "responses_response" in q["sql"]]
        assert about_responses and all('"match_hint"' not in sql for sql in about_responses)

    def test_it_is_named_for_what_it_is(self, client, root, world):
        answer, _text = download(client, ANSWERS)
        assert answer["Content-Disposition"] == (
            f'attachment; filename="surveys-with-answers-{today()}.csv"'
        )


@pytest.mark.django_db
class TestNeitherFileNamesAnyone:
    @pytest.mark.parametrize("address", [PLAIN, ANSWERS])
    def test_no_name_and_no_email_address(self, client, root, world, address):
        _answer, text = download(client, address)
        for account in [*world["people"], root]:
            assert account.email not in text
            if account.full_name:
                assert account.full_name not in text
        assert "@" not in text and "Example" not in text

    @pytest.mark.parametrize("address", [PLAIN, ANSWERS])
    def test_an_erased_person_keeps_their_row_by_number(self, client, root, world, address):
        account = world["bob"].account
        erasure.erase_account(account, by=root)
        _header, lines = rows(client, address)
        assert lines[world["bob"].pk]["account"] == str(account.pk)

    @pytest.mark.parametrize("address", [PLAIN, ANSWERS])
    def test_an_organizations_name_is_never_a_formula(self, client, root, world, address):
        Enterprise.objects.filter(pk=world["enterprise"].pk).update(name="=cmd|' /C calc'!A0")
        _header, lines = rows(client, address)
        assert lines[world["bob"].pk]["organization"] == "'=cmd|' /C calc'!A0"


@pytest.mark.django_db
class TestWhoMayDownload:
    def test_a_superuser_may_download_both(self, client, root, world):
        for address in (PLAIN, ANSWERS):
            assert client.get(address).status_code == 200
            assert client.post(address).status_code == 200

    def test_support_staff_get_the_file_without_answers_only(self, client, support, world):
        client.force_login(support)
        assert client.get(PLAIN).status_code == 200
        header, lines = rows(client, PLAIN)
        assert header == BASE and len(lines) == 2
        assert client.get(ANSWERS).status_code == 403
        assert client.post(ANSWERS).status_code == 403
        # The refused one left no record; the allowed one left one.
        assert [row.detail["answers"] for row in exported()] == [False]

    def test_staff_who_may_not_look_at_responses_get_neither(self, client, world):
        clerk = verified_account("clerk@example.com")
        Account.objects.filter(pk=clerk.pk).update(is_staff=True)
        client.force_login(clerk)
        for address in (PLAIN, ANSWERS):
            assert client.get(address).status_code == 403
            assert client.post(address).status_code == 403
        assert not exported().exists()

    def test_someone_who_is_not_staff_is_sent_to_the_admins_login(self, client, world):
        client.force_login(world["people"][0])
        for address in (PLAIN, ANSWERS):
            for answer in (client.get(address), client.post(address)):
                assert answer.status_code == 302 and "/admin/login/" in answer.url
        assert not exported().exists()

    def test_a_logged_out_visitor_too(self, client, world):
        for address in (PLAIN, ANSWERS):
            answer = client.post(address)
            assert answer.status_code == 302 and "/admin/login/" in answer.url


@pytest.mark.django_db
class TestEachDownloadIsRecorded:
    @pytest.mark.parametrize(("address", "answers"), [(PLAIN, False), (ANSWERS, True)])
    def test_who_how_many_rows_and_whether_the_answers_were_in_it(
        self, client, root, world, address, answers
    ):
        download(client, address)
        row = exported().get()
        assert row.actor_id == root.pk
        assert (row.target_type, row.target_id) == ("", "")
        assert row.detail == {"rows": 2, "answers": answers}

    def test_looking_at_the_page_records_nothing(self, client, root, world):
        for address in (PLAIN, ANSWERS):
            assert client.get(address).status_code == 200
        assert not exported().exists()

    def test_the_record_holds_no_name_or_address(self, client, root, world):
        download(client, ANSWERS)
        stored = str(exported().values().get())
        for word in ("Ann", "Bob", "Example", "@", "Acme"):
            assert word not in stored, word

    def test_the_record_is_written_before_the_first_line_is_sent(self, client, root, world):
        answer = client.post(ANSWERS)
        assert exported().count() == 1
        answer.close()


@pytest.mark.django_db
class TestThePagesInTheAdmin:
    def test_a_superuser_sees_both_buttons_on_the_responses_page(self, client, root, world):
        text = client.get(LIST).content.decode()
        assert f'<a href="{PLAIN}">Download as a spreadsheet…</a>' in text
        assert f'<a href="{ANSWERS}">Download with answers…</a>' in text

    def test_support_staff_see_only_the_one_without_answers(self, client, support, world):
        client.force_login(support)
        text = client.get(LIST).content.decode()
        assert f'<a href="{PLAIN}">' in text
        assert ANSWERS not in text and "with answers" not in text

    def test_the_page_says_what_the_file_holds_before_anything_is_sent(self, client, root, world):
        text = client.get(PLAIN).content.decode()
        assert "<h1>Download every submitted survey, without answers</h1>" in text
        assert "one row for each of the 2 submitted surveys" in text
        assert "The file holds no name and no email address." in text
        assert "It does not hold anyone's answers" in text
        assert "This download is recorded in the audit log" in text
        assert "Download the file" in text and "csrfmiddlewaretoken" in text

    @pytest.mark.parametrize("address", [PLAIN, ANSWERS])
    def test_the_button_carries_the_sites_security_token(self, root, world, address):
        """Without it another website could make a superuser's browser download and record."""
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(root)
        assert strict.post(address).status_code == 403
        assert not exported().exists()
        # The token of this page's own form: the admin's header has a log-out form with one too.
        form = strict.get(address).content.decode().split('id="content-main"')[1]
        token = form.split('name="csrfmiddlewaretoken" value="')[1].split('"')[0]
        assert strict.post(address, {"csrfmiddlewaretoken": token}).status_code == 200

    def test_the_page_for_the_file_with_answers_says_so(self, client, root, world):
        text = client.get(ANSWERS).content.decode()
        assert "<h1>Download every submitted survey, with answers</h1>" in text
        assert "It holds each person's answers" in text
        assert "delete it when you have finished with it" in text
        assert "It does not hold anyone's answers" not in text
        assert "took_before, took_before_via, q1, q2" in text

    def test_with_one_survey_the_page_says_survey_not_surveys(self, client, root, db):
        ann = named("ann@example.com", "Ann Example")
        give(ann, 1)
        take(ann)
        assert "the 1 submitted survey on the site" in client.get(PLAIN).content.decode()

    def test_with_no_survey_the_file_is_only_its_header(self, client, root):
        header, lines = rows(client, PLAIN)
        assert header == BASE and lines == {}
