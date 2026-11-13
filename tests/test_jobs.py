"""
Milestone 5, PR 1: the queue of background jobs and the worker.

What must hold. A job queued inside a transaction that is undone does not
exist. The worker does each job that is due, oldest first. A job that fails is
tried again later, waiting longer each time, and is marked failed after five
tries; it stops nothing else, and only the kind of error is kept. A job left
"running" by a worker that died is done again. Two workers never do the same
job. The site's own /health is untouched; /health/worker says whether the
worker is keeping up.
"""

import io
import logging
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Account
from apps.jobs import services as jobs
from apps.jobs.models import Job
from apps.responses.signals import GROUP_NAME

from .orgs import run_together
from .test_verification import PASSWORD

MINUTE = timedelta(minutes=1)


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


@pytest.fixture
def support(client, db):
    account = Account.objects.create_user("support@example.com", PASSWORD)
    account.is_staff = True
    account.save()
    account.groups.add(Group.objects.get(name=GROUP_NAME))
    client.force_login(account)
    return account


@pytest.fixture
def kinds(monkeypatch):
    """
    Three kinds of job for a test, registered for that test only: "note" writes
    down what it was given, "boom" always fails, "flaky" fails until told not to.
    """
    done, state = [], {"flaky_works": False}

    def note(**payload):
        done.append(payload)

    def boom(**payload):
        raise RuntimeError("carol@example.com could not be reached")

    def flaky(**payload):
        if not state["flaky_works"]:
            raise ConnectionError("the mail server said no to carol@example.com")
        done.append(payload)

    monkeypatch.setitem(jobs._handlers, "note", note)
    monkeypatch.setitem(jobs._handlers, "boom", boom)
    monkeypatch.setitem(jobs._handlers, "flaky", flaky)
    return type("Kinds", (), {"done": done, "state": state})


def later(minutes):
    return timezone.now() + minutes * MINUTE


def fresh(job):
    return Job.objects.get(pk=job.pk)


# --- adding a job --------------------------------------------------------------------------


@pytest.mark.django_db
class TestQueuingAJob:
    def test_a_job_waits_in_the_queue_with_what_it_was_given(self, kinds):
        queued = jobs.enqueue("note", {"entitlement_id": 12})
        assert (queued.kind, queued.status, queued.attempts) == ("note", "queued", 0)
        assert queued.payload == {"entitlement_id": 12} and queued.max_attempts == 5
        assert str(queued) == f"Job {queued.pk} (note)"
        assert kinds.done == []  # nothing is done until the worker runs

    def test_a_kind_nobody_registered_is_refused_at_once(self):
        with pytest.raises(jobs.UnknownKind):
            jobs.enqueue("a_typo")
        assert not Job.objects.exists()

    def test_a_job_queued_in_a_transaction_that_is_undone_does_not_exist(self, kinds):
        with pytest.raises(RuntimeError), transaction.atomic():
            jobs.enqueue("note", {"n": 1})
            raise RuntimeError("the licence could not be given after all")
        assert not Job.objects.exists()

    def test_the_site_starts_knowing_the_test_job(self):
        assert jobs.TEST_KIND in jobs.kinds()


# --- doing the jobs ------------------------------------------------------------------------


@pytest.mark.django_db
class TestDoingTheJobs:
    def test_jobs_are_done_oldest_first_and_each_once(self, kinds):
        for number in (1, 2, 3):
            jobs.enqueue("note", {"n": number})
        assert jobs.run_due() == 3
        assert kinds.done == [{"n": 1}, {"n": 2}, {"n": 3}]
        assert jobs.run_due() == 0 and len(kinds.done) == 3
        for done in Job.objects.all():
            assert (done.status, done.attempts, done.last_error) == ("done", 1, "")
            assert done.finished_at is not None and done.locked_at is None

    def test_a_job_for_later_waits_until_then(self, kinds):
        queued = jobs.enqueue("note", {"n": 1}, run_after=later(5))
        assert jobs.run_due() == 0 and kinds.done == []
        assert jobs.run_due(now=later(6)) == 1 and fresh(queued).status == "done"

    def test_with_nothing_to_do_it_says_so(self):
        assert jobs.run_one() is False

    def test_a_failing_job_is_put_back_for_later_and_stops_nothing_else(self, kinds, caplog):
        bad = jobs.enqueue("boom")
        jobs.enqueue("note", {"n": 1})
        with caplog.at_level(logging.ERROR, logger="apps.jobs.services"):
            assert jobs.run_due() == 2
        assert kinds.done == [{"n": 1}]
        now = fresh(bad)
        assert (now.status, now.attempts, now.last_error) == ("queued", 1, "RuntimeError")
        assert now.finished_at is None and now.locked_at is None
        assert timedelta(seconds=110) < now.run_after - timezone.now() < timedelta(seconds=125)
        # Staff are told, and neither the log nor the row repeats the error's own words.
        assert f"Job {bad.pk} (boom) failed on try 1 of 5: RuntimeError" in caplog.text
        assert "carol" not in caplog.text and "carol" not in now.last_error

    def test_it_waits_longer_each_time_and_gives_up_after_five_tries(self, kinds):
        bad = jobs.enqueue("boom")
        waits = []
        for _ in range(5):
            before = timezone.now()
            assert jobs.run_one(now=later(60)) is True
            now = fresh(bad)
            if now.status == "queued":
                waits.append(round((now.run_after - before).total_seconds() / 60))
        assert waits == [2, 4, 8, 16]
        assert (now.status, now.attempts, now.last_error) == ("failed", 5, "RuntimeError")
        assert now.finished_at is not None
        assert jobs.run_one(now=later(600)) is False  # a failed job is left alone

    def test_a_job_that_starts_working_again_is_done(self, kinds):
        queued = jobs.enqueue("flaky", {"n": 7})
        jobs.run_one()
        kinds.state["flaky_works"] = True
        assert jobs.run_one(now=later(3)) is True
        now = fresh(queued)
        assert (now.status, now.attempts, now.last_error) == ("done", 2, "")
        assert kinds.done == [{"n": 7}]

    def test_what_a_failing_job_wrote_is_undone(self, kinds, monkeypatch):
        def writes_then_fails(**payload):
            jobs.enqueue("note", {"left": "behind"})
            raise RuntimeError("after writing")

        monkeypatch.setitem(jobs._handlers, "boom", writes_then_fails)
        jobs.enqueue("boom")
        jobs.run_one()
        assert Job.objects.filter(kind="note").count() == 0

    def test_a_kind_that_has_gone_fails_for_good_without_stopping_the_others(self, kinds):
        orphan = Job.objects.create(kind="removed_in_a_later_version")
        jobs.enqueue("note", {"n": 1})
        assert jobs.run_due() == 2 and kinds.done == [{"n": 1}]
        now = fresh(orphan)
        assert (now.status, now.attempts, now.last_error) == ("failed", 1, "UnknownKind")

    def test_a_job_a_dead_worker_left_running_is_done_again(self, kinds):
        queued = jobs.enqueue("note", {"n": 1})
        Job.objects.filter(pk=queued.pk).update(
            status="running", attempts=1, locked_at=timezone.now() - 11 * MINUTE
        )
        fine = jobs.enqueue("note", {"n": 2})
        Job.objects.filter(pk=fine.pk).update(
            status="running", attempts=1, locked_at=timezone.now() - 2 * MINUTE
        )
        assert jobs.requeue_stuck() == 1
        assert fresh(queued).status == "queued" and fresh(fine).status == "running"
        jobs.run_due()
        assert kinds.done == [{"n": 1}] and fresh(queued).attempts == 2

    def test_staff_can_put_a_failed_job_back_with_a_fresh_count(self, kinds):
        bad = jobs.enqueue("flaky", {"n": 1})
        Job.objects.filter(pk=bad.pk).update(
            status="failed", attempts=5, finished_at=timezone.now(), last_error="ConnectionError"
        )
        done = jobs.enqueue("note")
        jobs.run_due()
        assert jobs.retry(fresh(bad)) == 1 and jobs.retry(fresh(done)) == 0
        kinds.state["flaky_works"] = True
        jobs.run_due()
        assert (fresh(bad).status, fresh(bad).attempts) == ("done", 1)


@pytest.mark.django_db(transaction=True)
def test_two_workers_at_once_never_do_the_same_job(monkeypatch):
    done = []
    monkeypatch.setitem(jobs._handlers, "note", lambda **payload: done.append(payload["n"]))
    for number in range(6):
        jobs.enqueue("note", {"n": number})
    results = run_together(*[lambda: jobs.run_due() for _ in range(3)])
    assert sum(results) == 6, results
    assert sorted(done) == [0, 1, 2, 3, 4, 5]
    assert Job.objects.filter(status="done", attempts=1).count() == 6


# --- the worker command ---------------------------------------------------------------------


@pytest.mark.django_db
class TestTheWorkerCommand:
    def test_once_does_what_is_due_and_stops(self, kinds):
        jobs.enqueue("note", {"n": 1})
        jobs.enqueue("note", {"n": 2}, run_after=later(30))
        out = io.StringIO()
        call_command("run_worker", "--once", stdout=out)
        assert kinds.done == [{"n": 1}]
        assert "Worker started." in out.getvalue() and "Worker stopped." in out.getvalue()
        assert jobs.TEST_KIND in out.getvalue()

    def test_once_also_picks_up_what_a_dead_worker_left(self, kinds):
        queued = jobs.enqueue("note", {"n": 1})
        Job.objects.filter(pk=queued.pk).update(
            status="running", locked_at=timezone.now() - 11 * MINUTE
        )
        call_command("run_worker", "--once", stdout=io.StringIO())
        assert kinds.done == [{"n": 1}]

    def test_a_failing_job_does_not_stop_the_command(self, kinds):
        jobs.enqueue("boom")
        jobs.enqueue("note", {"n": 1})
        call_command("run_worker", "--once", stdout=io.StringIO())
        assert kinds.done == [{"n": 1}]

    def test_asked_to_stop_it_finishes_the_job_in_hand_and_leaves(self, kinds, monkeypatch):
        from apps.jobs.management.commands.run_worker import Command

        command = Command(stdout=io.StringIO())
        seen = []

        def one_then_stop(now=None):
            seen.append("job")
            command.stop(None, None)  # the signal arrives while a job is being done
            return True

        monkeypatch.setattr(jobs, "run_one", one_then_stop)
        monkeypatch.setattr("signal.signal", lambda *args: None)
        command.handle(once=False)
        assert seen == ["job"]  # it did not start another


# --- is the worker keeping up? --------------------------------------------------------------


@pytest.mark.django_db
class TestIsTheWorkerKeepingUp:
    def test_an_empty_queue_is_fine(self, client):
        assert jobs.waiting() == {"count": 0, "oldest": None, "behind": False}
        answer = client.get("/health/worker")
        assert answer.status_code == 200 and answer.content == b"ok"

    def test_a_job_that_has_just_been_queued_is_fine(self, client, kinds):
        jobs.enqueue("note")
        jobs.enqueue("note", run_after=later(60))  # not due yet: not waiting
        queue = jobs.waiting()
        assert queue["count"] == 1 and queue["behind"] is False
        assert client.get("/health/worker").status_code == 200

    def test_a_job_due_for_more_than_ten_minutes_means_behind(self, client, kinds):
        queued = jobs.enqueue("note")
        Job.objects.filter(pk=queued.pk).update(run_after=timezone.now() - 11 * MINUTE)
        assert jobs.waiting()["behind"] is True
        answer = client.get("/health/worker")
        assert answer.status_code == 503 and answer.content == b"behind"

    def test_the_sites_own_health_does_not_look_at_the_queue(
        self, client, kinds, django_assert_num_queries
    ):
        queued = jobs.enqueue("note")
        Job.objects.filter(pk=queued.pk).update(run_after=timezone.now() - 60 * MINUTE)
        with django_assert_num_queries(0):
            answer = client.get("/health")
        assert answer.status_code == 200 and answer.content == b"ok"


# --- the Jobs page of the admin -------------------------------------------------------------


@pytest.mark.django_db
class TestTheJobsPage:
    PAGE = "/admin/jobs/job/"

    def test_it_says_how_the_queue_stands(self, client, root, kinds):
        assert "No job is waiting." in client.get(self.PAGE).content.decode()
        queued = jobs.enqueue("note")
        Job.objects.filter(pk=queued.pk).update(run_after=timezone.now() - 3 * MINUTE)
        text = client.get(self.PAGE).content.decode()
        assert "1 job(s) waiting; the oldest has waited about 3 minutes." in text
        assert "not keeping up" not in text
        Job.objects.filter(pk=queued.pk).update(run_after=timezone.now() - 45 * MINUTE)
        text = client.get(self.PAGE).content.decode()
        assert "about 45 minutes. The worker is not keeping up, or is not running." in text

    def test_a_superuser_queues_a_test_job_and_sees_it_done_once_the_worker_runs(
        self, client, root
    ):
        assert "Queue a test job" in client.get(self.PAGE).content.decode()
        answer = client.post(self.PAGE + "queue-a-test-job/")
        assert answer.status_code == 302 and answer["Location"] == self.PAGE
        queued = Job.objects.get()
        (said,) = [str(message) for message in get_messages(answer.wsgi_request)]
        assert said.startswith(f"Job {queued.pk} (test_job) is in the queue.")
        assert queued.status == "queued"
        jobs.run_due()
        assert "Done" in client.get(self.PAGE).content.decode()
        assert (
            client.get(self.PAGE + "queue-a-test-job/").status_code == 405
        )  # a button, not a link

    def test_a_superuser_runs_a_failed_job_again(self, client, root, kinds):
        bad = jobs.enqueue("flaky")
        Job.objects.filter(pk=bad.pk).update(status="failed", attempts=5, last_error="OSError")
        client.post(self.PAGE, {"action": "run_again", "_selected_action": [bad.pk]})
        assert (fresh(bad).status, fresh(bad).attempts) == ("queued", 0)

    def test_nothing_can_be_typed_added_or_deleted(self, client, root, kinds):
        queued = jobs.enqueue("note", {"entitlement_id": 12})
        page = client.get(f"{self.PAGE}{queued.pk}/change/")
        assert page.status_code == 200 and "entitlement_id" in page.content.decode()
        assert client.post(f"{self.PAGE}{queued.pk}/change/", {"kind": "x"}).status_code == 403
        assert client.get(self.PAGE + "add/").status_code == 403
        assert client.get(f"{self.PAGE}{queued.pk}/delete/").status_code == 403

    def test_support_staff_can_look_and_can_neither_test_nor_run_again(
        self, client, support, kinds
    ):
        bad = jobs.enqueue("flaky")
        Job.objects.filter(pk=bad.pk).update(status="failed", attempts=5)
        text = client.get(self.PAGE).content.decode()
        assert "job(s) waiting" in text or "No job is waiting." in text
        assert "Queue a test job" not in text and "Run the selected failed jobs again" not in text
        assert client.post(self.PAGE + "queue-a-test-job/").status_code == 403
        client.post(self.PAGE, {"action": "run_again", "_selected_action": [bad.pk]})
        assert fresh(bad).status == "failed" and Job.objects.count() == 1
