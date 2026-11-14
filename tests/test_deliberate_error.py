"""
Milestone 7: "Send a test error", on the Background jobs page of the Django admin.

The only way to know that error reports reach Sentry is to cause an error and
look. A superuser can now do that without SSH: one press fails this request on
purpose (the web site's report) and queues a job that fails once in the worker
(the worker's report) and is done on its second try, so nothing stays broken.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.jobs import services as jobs
from apps.jobs.models import Job

from .test_support_staff_admin import root, support  # noqa: F401

LIST = reverse("admin:jobs_job_changelist")
PAGE = reverse("admin:jobs_job_test_error")


def later(job):
    """Pretend the wait before the next try is over."""
    Job.objects.filter(pk=job.pk).update(run_after=timezone.now() - timedelta(seconds=1))


@pytest.mark.django_db
class TestThePage:
    def test_a_superuser_finds_it_from_the_jobs_page(self, client, root):
        assert f'<a href="{PAGE}">Send a test error…</a>' in client.get(LIST).content.decode()

    def test_it_says_what_will_happen_and_does_nothing_until_pressed(self, client, root):
        text = client.get(PAGE).content.decode()
        assert "This sends two errors on purpose" in text
        assert "That is the test working, not a fault." in text
        assert "csrfmiddlewaretoken" in text.split('id="content-main"')[1]
        assert not Job.objects.exists()

    def test_pressing_it_fails_this_request_on_purpose(self, client, root):
        with pytest.raises(jobs.DeliberateError, match="on purpose"):
            client.post(PAGE)

    def test_what_the_superuser_sees_is_the_calm_page(self, client, root):
        client.raise_request_exception = False
        answer = client.post(PAGE)
        assert answer.status_code == 500
        assert "<h1>Something went wrong</h1>" in answer.content.decode()

    def test_and_a_job_is_left_for_the_worker(self, client, root):
        client.raise_request_exception = False
        client.post(PAGE)
        queued = Job.objects.get()
        assert (queued.kind, queued.status) == ("test_error", "queued")
        assert set(queued.payload) == {"token"}

    def test_support_staff_have_neither_the_link_nor_the_page(self, client, support):
        client.force_login(support)
        assert "Send a test error" not in client.get(LIST).content.decode()
        assert client.get(PAGE).status_code == 403
        assert client.post(PAGE).status_code == 403
        assert not Job.objects.exists()


@pytest.mark.django_db
class TestTheJobInTheWorker:
    def test_it_fails_once_which_is_what_tells_sentry(self, caplog):
        queued = jobs.send_test_error()
        assert jobs.run_due() == 1
        queued.refresh_from_db()
        assert (queued.status, queued.attempts, queued.last_error) == (
            "queued",
            1,
            "DeliberateError",
        )
        # The worker's own log line is what Sentry picks up; it names the kind of error only.
        assert "failed on try 1 of 5: DeliberateError" in caplog.text

    def test_and_is_done_on_its_second_try(self):
        queued = jobs.send_test_error()
        jobs.run_due()
        assert jobs.run_due() == 0  # not due again for two minutes
        later(queued)
        assert jobs.run_due() == 1
        queued.refresh_from_db()
        assert (queued.status, queued.attempts, queued.last_error) == ("done", 2, "")
        assert not Job.objects.filter(status="failed").exists()

    def test_two_tests_do_not_confuse_each_other(self):
        first = jobs.send_test_error()
        jobs.run_due()
        later(first)
        second = jobs.send_test_error()
        jobs.run_due()
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == "done"
        assert (second.status, second.last_error) == ("queued", "DeliberateError")

    def test_the_site_starts_knowing_how_to_do_it(self):
        assert jobs.TEST_ERROR_KIND in jobs.kinds()
