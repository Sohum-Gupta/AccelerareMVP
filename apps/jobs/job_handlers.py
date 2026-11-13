"""The jobs this app itself knows how to do: one, which does nothing."""

from . import services


@services.job(services.TEST_KIND)
def test_job():
    """
    Queued from the admin's "Queue a test job" button. If it shows as done a
    few seconds later, the worker is alive and reading the queue.
    """
