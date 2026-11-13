"""
Milestone 6, PR 4: the numbers at the top of the Django admin's first page.

Accounts, organizations, surveys submitted (in the last seven days and in
all), possible duplicates waiting for a decision, and background jobs that
failed or are waiting. Each number is a link to the list behind it, and that
list shows the same number of rows. A member of staff sees only the numbers
for lists they may open.

The world: Ann submitted a survey today and Bea twelve days ago; Cy has
started one; Dee submitted one today and was then erased. One organization. Two possible duplicates, one
waiting and one decided. Three background jobs: one failed, two waiting.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.jobs.models import Job
from apps.matching.models import MatchCandidate
from apps.responses import services as surveys
from apps.responses.models import Response
from apps.responses.staff_numbers import numbers_for

from .orgs import org_with_admin
from .test_matching import give, take
from .test_profile import verified_account
from .test_staff_export import named
from .test_support_staff_admin import root, support  # noqa: F401

INDEX = reverse("admin:index")

ACCOUNTS = "Accounts (not counting erased ones)"
ORGANIZATIONS = "Organizations"
RECENT = "Surveys submitted in the last 7 days"
ALL_TIME = "Surveys submitted, all time"
DUPLICATES = "Possible duplicates waiting for a decision"
FAILED = "Background jobs that failed"
WAITING = "Background jobs waiting"


@pytest.fixture
def world(db):
    ann = named("ann@example.com", "Ann Example")
    give(ann, 1)
    take(ann)

    bea = named("bea@example.com", "Bea Example")
    give(bea, 1)
    old = take(bea)
    Response.objects.filter(pk=old.pk).update(submitted_at=timezone.now() - timedelta(days=12))

    cy = named("cy@example.com", "Cy Example")
    give(cy, 1)
    surveys.start_response(cy)

    dee = named("dee@example.com", "Dee Example")
    give(dee, 1)
    take(dee)
    erasure.erase_account(dee)  # her survey is kept, so the account stays, stripped

    org_with_admin("Acme")  # a fifth account, its admin

    first, second = sorted([ann.pk, bea.pk])
    MatchCandidate.objects.create(account_a_id=first, account_b_id=second, signals={})
    first, second = sorted([ann.pk, cy.pk])
    MatchCandidate.objects.create(
        account_a_id=first, account_b_id=second, signals={}, status="rejected"
    )

    Job.objects.all().delete()  # whatever the steps above queued
    Job.objects.create(kind="test_job", status="failed")
    Job.objects.create(kind="test_job")
    Job.objects.create(kind="test_job", run_after=timezone.now() + timedelta(hours=1))


def shown(client):
    """The panel as the page shows it: {label: (number, address, warning)}."""
    page = client.get(INDEX)
    assert page.status_code == 200
    text = page.content.decode()
    if "data-staff-numbers" not in text:
        return {}
    panel = text.split("data-staff-numbers")[1].split("</table>")[0]
    lines = {}
    for row in panel.split("<tr>")[1:]:
        label = row.split("</a>")[0].split(">")[-1]
        address = row.split('href="')[1].split('"')[0].replace("&amp;", "&")
        number = int(row.split("<strong>")[1].split("</strong>")[0])
        warning = (
            row.split('class="errornote"')[1].split(">")[1].split("<")[0]
            if "errornote" in row
            else ""
        )
        lines[label] = (number, address, warning)
    return lines


@pytest.mark.django_db
class TestASuperuser:
    def test_sees_every_number(self, client, world, root):
        numbers = {label: number for label, (number, _address, _warning) in shown(client).items()}
        assert numbers == {
            ACCOUNTS: 5,  # Ann, Bea, Cy, Acme's admin and the superuser; not Dee
            ORGANIZATIONS: 1,
            RECENT: 2,  # Ann's and Dee's; Bea's is twelve days old
            ALL_TIME: 3,
            DUPLICATES: 1,
            FAILED: 1,
            WAITING: 2,
        }

    def test_each_number_opens_a_list_with_that_many_rows(self, client, world, root):
        lines = shown(client)
        assert len(lines) == 7
        for label, (number, address, _warning) in lines.items():
            page = client.get(address)
            assert page.status_code == 200, label
            assert page.context["cl"].result_count == number, label

    def test_the_rest_of_the_page_is_still_djangos(self, client, world, root):
        text = client.get(INDEX).content.decode()
        assert "At a glance" in text
        assert reverse("admin:accounts_account_changelist") in text
        assert "Recent actions" in text
        # The panel comes before the list of pages.
        assert text.index("data-staff-numbers") < text.index('class="app-accounts')

    def test_the_panel_names_nobody(self, client, world, root):
        panel = (
            client.get(INDEX).content.decode().split("data-staff-numbers")[1].split("</table>")[0]
        )
        for word in ("Ann", "Bea", "Example", "@", "Acme"):
            assert word not in panel, word


@pytest.mark.django_db
class TestWhatCountsAsRecent:
    def submitted(self, days_ago):
        account = verified_account(f"p{days_ago}@example.com")
        give(account, 1)
        response = take(account)
        when = timezone.now() - timedelta(days=days_ago)
        Response.objects.filter(pk=response.pk).update(submitted_at=when)

    def test_seven_days_back_counts_and_eight_does_not(self, client, root):
        for days_ago in (0, 6, 7, 8, 30):
            self.submitted(days_ago)
        number, address, _warning = shown(client)[RECENT]
        assert number == 3
        assert client.get(address).context["cl"].result_count == 3

    def test_the_list_it_opens_has_past_7_days_chosen_in_its_date_filter(self, client, root):
        self.submitted(1)
        _number, address, _warning = shown(client)[RECENT]
        text = client.get(address).content.decode()
        chosen = re.findall(r'<li class="selected">\s*<a [^>]*>([^<]+)</a>', text)
        assert "Past 7 days" in chosen

    def test_an_unfinished_survey_is_never_counted(self, client, root):
        cy = verified_account("cy@example.com")
        give(cy, 1)
        surveys.start_response(cy)
        lines = shown(client)
        assert lines[RECENT][0] == 0 and lines[ALL_TIME][0] == 0


@pytest.mark.django_db
class TestWarnings:
    def test_nothing_is_flagged_when_all_is_well(self, client, root):
        assert [warning for _n, _a, warning in shown(client).values()] == [""] * 7

    def test_a_failed_job_is_flagged(self, client, world, root):
        assert shown(client)[FAILED][2] == "open the list to see why, and to run them again"

    def test_jobs_that_have_waited_too_long_are_flagged(self, client, root):
        Job.objects.create(kind="test_job", run_after=timezone.now() - timedelta(minutes=30))
        assert shown(client)[WAITING] == (
            1,
            reverse("admin:jobs_job_changelist") + "?status__exact=queued",
            "the worker is not keeping up, or is not running",
        )

    def test_a_job_that_has_only_just_been_queued_is_not(self, client, root):
        Job.objects.create(kind="test_job")
        assert shown(client)[WAITING][2] == ""


@pytest.mark.django_db
class TestOtherStaff:
    def test_support_staff_see_all_but_the_possible_duplicates(self, client, world, support):
        client.force_login(support)
        lines = shown(client)
        assert list(lines) == [ACCOUNTS, ORGANIZATIONS, RECENT, ALL_TIME, FAILED, WAITING]
        for label, (number, address, _warning) in lines.items():
            page = client.get(address)
            assert page.status_code == 200, label
            assert page.context["cl"].result_count == number, label

    def test_a_number_they_may_not_see_is_not_even_counted(
        self, world, support, rf, django_assert_num_queries
    ):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        request = rf.get(INDEX)
        request.user = Account.objects.get(pk=support.pk)
        with CaptureQueriesContext(connection) as queries:
            numbers_for(request)
        assert not [q for q in queries if "matching_matchcandidate" in q["sql"]]

    def test_staff_with_no_permissions_see_no_panel(self, client, world):
        clerk = verified_account("clerk@example.com")
        Account.objects.filter(pk=clerk.pk).update(is_staff=True)
        client.force_login(clerk)
        assert shown(client) == {}
        assert "At a glance" not in client.get(INDEX).content.decode()

    def test_someone_who_is_not_staff_never_reaches_the_page(self, client, world):
        client.force_login(Account.objects.get(email="ann@example.com"))
        answer = client.get(INDEX)
        assert answer.status_code == 302 and "/admin/login/" in answer.url
