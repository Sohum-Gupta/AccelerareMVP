"""
Milestone 5, PR 6: the place the algorithm's results will go.

There is no algorithm yet. What exists is the path a result will take, so that
nothing else has to change when one arrives: submitting a survey queues a job;
the worker hands the response to `compute_result`; whatever that returns is
stored whole; and a tier filter decides what a person may see of it. Today
`compute_result` returns nothing, so nothing is stored.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.jobs import services as jobs
from apps.jobs.models import Job
from apps.responses import services as surveys
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME
from apps.results import algorithm, tiering
from apps.results import services as results
from apps.results.models import Result

from .test_matching import OTHER_PHONE, PASSWORD, give, someone, take

WORKED_OUT = {"summary": "made up", "detail": [1, 2, 3], "deep": {"made": "up"}}


@pytest.fixture
def ann(db):
    account = someone("ann@example.com", OTHER_PHONE)
    give(account, 2)
    return account


@pytest.fixture
def submitted(ann):
    return take(ann)


@pytest.fixture
def an_algorithm(monkeypatch):
    """Stand in for the algorithm that does not exist yet: it returns a made-up result."""
    monkeypatch.setattr(algorithm, "compute_result", lambda response: dict(WORKED_OUT))


def result_jobs(response=None):
    found = Job.objects.filter(kind=results.COMPUTE_RESULT)
    return found.filter(payload={"response_id": response.pk}) if response else found


# --- today: no algorithm ----------------------------------------------------------------------


@pytest.mark.django_db
class TestWithNoAlgorithm:
    def test_submitting_queues_the_job_with_the_responses_number_only(self, submitted):
        job = result_jobs().get()
        assert job.payload == {"response_id": submitted.pk} and job.status == "queued"

    def test_the_worker_runs_it_and_nothing_is_stored(self, submitted):
        jobs.run_due()
        assert result_jobs().get().status == "done" and not Result.objects.exists()
        assert results.latest_for(submitted) is None
        assert results.visible_result(submitted, 3) is None

    def test_the_algorithm_is_at_version_zero_and_returns_nothing(self, submitted):
        assert algorithm.ALGORITHM_VERSION == "0.0.0"
        assert algorithm.compute_result(submitted) is None

    def test_the_result_page_still_says_results_are_being_prepared(self, client, ann, submitted):
        jobs.run_due()
        client.force_login(ann)
        page = client.get(reverse("responses:result", args=[submitted.pk])).content.decode()
        assert "They are being prepared in a later update." in page

    def test_an_unfinished_survey_queues_nothing(self, ann):
        surveys.save_self_report(surveys.start_response(ann), False)
        assert not result_jobs().exists()


# --- when there is one ------------------------------------------------------------------------


@pytest.mark.django_db
class TestWithAnAlgorithm:
    def test_what_it_returns_is_stored_whole_with_its_version(self, submitted, an_algorithm):
        jobs.run_due()
        result = Result.objects.get()
        assert result.response == submitted and result.payload == WORKED_OUT
        assert result.algorithm_version == "0.0.0" and result.computed_at is not None
        assert results.latest_for(submitted) == result

    def test_run_twice_it_is_still_one_row_with_the_newer_answer(
        self, submitted, an_algorithm, monkeypatch
    ):
        first = results.compute_and_store(submitted)
        monkeypatch.setattr(algorithm, "compute_result", lambda response: {"summary": "changed"})
        second = results.compute_and_store(submitted)
        assert second.pk == first.pk and Result.objects.count() == 1
        assert Result.objects.get().payload == {"summary": "changed"}
        assert second.computed_at >= first.computed_at

    def test_a_new_version_adds_a_row_and_the_newest_is_the_one_shown(
        self, submitted, an_algorithm, monkeypatch
    ):
        old = results.compute_and_store(submitted)
        monkeypatch.setattr(algorithm, "ALGORITHM_VERSION", "1.0.0")
        new = results.compute_and_store(submitted)
        assert new.pk != old.pk and Result.objects.count() == 2
        assert results.latest_for(submitted) == new

    def test_each_survey_has_its_own_result(self, ann, an_algorithm, monkeypatch):
        give(ann)
        first, second = take(ann), take(ann)
        mine = results.compute_and_store(first)
        monkeypatch.setattr(algorithm, "compute_result", lambda response: {"summary": "other"})
        theirs = results.compute_and_store(second)
        assert results.latest_for(first) == mine and results.latest_for(second) == theirs
        assert results.visible_result(first, 3) == WORKED_OUT

    def test_a_job_for_a_response_that_has_gone_or_is_not_submitted_stores_nothing(
        self, ann, an_algorithm
    ):
        draft = surveys.save_self_report(surveys.start_response(ann), False)
        jobs.enqueue(results.COMPUTE_RESULT, {"response_id": draft.pk})
        jobs.enqueue(results.COMPUTE_RESULT, {"response_id": 999_999})
        jobs.run_due()
        assert not Result.objects.exists()
        assert not result_jobs().exclude(status="done").exists()

    def test_an_algorithm_that_fails_never_touches_the_submission(self, ann, monkeypatch):
        def broken(response):
            raise ZeroDivisionError("the algorithm has a bug")

        monkeypatch.setattr(algorithm, "compute_result", broken)
        response = take(ann)  # submitting works: the algorithm is not run here
        jobs.run_due()
        job = result_jobs(response).get()
        assert job.status == "queued" and job.attempts == 1  # waiting to be tried again
        assert job.last_error == "ZeroDivisionError"
        assert Response.objects.get(pk=response.pk).status == "submitted"
        assert not Result.objects.exists()

    def test_the_command_queues_every_submitted_survey_again(self, ann, capsys):
        give(ann), give(ann)
        first, second = take(ann), take(ann)
        surveys.save_self_report(surveys.start_response(ann), False)  # a draft: left out
        Job.objects.all().delete()
        call_command("recompute_results")
        assert "Queued 2 submitted survey(s)" in capsys.readouterr().out
        assert result_jobs(first).count() == 1 and result_jobs(second).count() == 1
        assert result_jobs().count() == 2

    def test_run_after_a_change_the_command_brings_old_surveys_up_to_date(
        self, submitted, an_algorithm, monkeypatch
    ):
        jobs.run_due()
        monkeypatch.setattr(algorithm, "ALGORITHM_VERSION", "1.0.0")
        call_command("recompute_results")
        jobs.run_due()
        assert sorted(Result.objects.values_list("algorithm_version", flat=True)) == [
            "0.0.0",
            "1.0.0",
        ]


# --- what a tier may see ----------------------------------------------------------------------


class TestTiers:
    def test_until_the_map_is_filled_every_tier_sees_everything(self):
        assert tiering.FIELD_TIERS == {}
        for tier in (1, 2, 3):
            assert tiering.visible_fields(WORKED_OUT, tier) == WORKED_OUT

    def test_a_field_is_shown_from_its_lowest_tier_upwards(self, monkeypatch):
        monkeypatch.setattr(tiering, "FIELD_TIERS", {"detail": 2, "deep": 3})
        assert set(tiering.visible_fields(WORKED_OUT, 1)) == {"summary"}
        assert set(tiering.visible_fields(WORKED_OUT, 2)) == {"summary", "detail"}
        assert tiering.visible_fields(WORKED_OUT, 3) == WORKED_OUT

    @pytest.mark.django_db
    def test_an_upgrade_shows_more_of_the_same_stored_result(
        self, submitted, an_algorithm, monkeypatch
    ):
        monkeypatch.setattr(tiering, "FIELD_TIERS", {"detail": 2, "deep": 3})
        results.compute_and_store(submitted)
        assert set(results.visible_result(submitted, 2)) == {"summary", "detail"}
        assert results.visible_result(submitted, 3) == WORKED_OUT
        assert Result.objects.count() == 1  # nothing was worked out again


# --- erasing, and who can look ----------------------------------------------------------------


@pytest.mark.django_db
class TestErasingAndLooking:
    def test_results_are_kept_with_the_survey_when_a_person_is_stripped(
        self, ann, submitted, an_algorithm
    ):
        results.compute_and_store(submitted)
        assert erasure.erase_account(ann).action == erasure.ANONYMISE
        assert Result.objects.get().response == submitted

    def test_a_result_goes_when_its_response_does(self, submitted, an_algorithm):
        results.compute_and_store(submitted)
        Response.objects.filter(pk=submitted.pk).delete()
        assert not Result.objects.exists()

    def test_only_a_superuser_sees_results_in_the_admin_and_nobody_edits_them(
        self, client, submitted, an_algorithm
    ):
        result = results.compute_and_store(submitted)
        listing = reverse("admin:results_result_changelist")
        one = reverse("admin:results_result_change", args=[result.pk])
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        assert client.get(listing).status_code == 200 and client.get(one).status_code == 200
        assert client.get(reverse("admin:results_result_add")).status_code == 403
        delete = reverse("admin:results_result_delete", args=[result.pk])
        assert client.post(delete, {"post": "yes"}).status_code == 403
        client.post(one, {"algorithm_version": "9.9.9"})
        assert Result.objects.get().algorithm_version == "0.0.0"
        support = Account.objects.create_user("support@example.com", PASSWORD, is_staff=True)
        support.groups.add(Group.objects.get(name=GROUP_NAME))
        client.force_login(support)
        assert client.get(listing).status_code == 403 and client.get(one).status_code == 403
        assert ">Results<" not in client.get(reverse("admin:index")).content.decode()
