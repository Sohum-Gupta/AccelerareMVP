"""The jobs this app itself knows how to do: one that does nothing, and one that fails once on purpose."""

from . import services
from .models import Job


@services.job(services.TEST_KIND)
def test_job():
    """
    Queued from the admin's "Queue a test job" button. If it shows as done a
    few seconds later, the worker is alive and reading the queue.
    """


@services.job(services.TEST_ERROR_KIND)
def test_error(token):
    """
    Queued from the admin's "Send a test error" page. It fails on purpose the
    first time it is tried, so that the worker reports an error to Sentry, and
    does nothing on the second try two minutes later, so that it ends as
    "Done" and nothing is left looking broken.

    It knows which try this is from its own row: the worker counts the try
    and saves that before it runs the job.
    """
    tries = (
        Job.objects.filter(kind=services.TEST_ERROR_KIND, payload__token=token)
        .values_list("attempts", flat=True)
        .first()
    )
    if tries is None or tries <= 1:
        raise services.DeliberateError("A test error, sent on purpose. Nothing is wrong.")
