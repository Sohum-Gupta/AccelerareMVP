"""
Every write to the queue of background jobs goes through here.

How it is used:

    from apps.jobs import services as jobs

    jobs.enqueue("send_licence_email", {"entitlement_id": 12})

and, in the app that knows how to do it, in a file called job_handlers.py:

    @jobs.job("send_licence_email")
    def send_licence_email(entitlement_id):
        ...

The rules:

* enqueue writes a row inside the caller's transaction. If the caller's work is
  undone, the job goes with it, so there is never a job for something that did
  not happen.
* The worker runs each job at least once. It can die after doing one and before
  recording it, and the job then runs again. So every handler must be safe to
  run twice.
* A job that fails is tried again later, waiting longer each time (2, 4, 8 and
  16 minutes), and is marked failed after five tries. A failed job stops
  nothing else, and staff can run it again from the admin.
* A payload holds plain numbers and words, never personal data. `last_error`
  holds only the kind of error, never its message.

run_one is the heart of the worker: it claims the oldest job that is due,
commits that claim, runs the job in a transaction of its own, and records what
happened. `skip_locked` means a second worker would simply take the next job.
"""

import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Job

logger = logging.getLogger(__name__)

# A job still "running" after this long was being done by a worker that died.
STUCK_AFTER = timedelta(minutes=10)
# The worker is "behind" when a job has been due for longer than this.
BEHIND_AFTER = timedelta(minutes=10)
# What staff queue from the admin to see that the worker is alive. It does nothing.
TEST_KIND = "test_job"
# What a superuser queues from the admin to see an error arrive in Sentry from
# the worker. It fails on purpose, once, and is done on its second try.
TEST_ERROR_KIND = "test_error"

_handlers = {}


class UnknownKind(Exception):
    """No function is registered for this kind of job."""


class DeliberateError(Exception):
    """
    An error raised on purpose, from the admin's "Send a test error" page, to
    see that error reports reach Sentry. Nothing is wrong when this appears.
    """


def job(kind):
    """Register the function that does jobs of this kind. Used as a decorator."""

    def register(function):
        _handlers[kind] = function
        return function

    return register


def kinds():
    """The kinds of job the site knows how to do."""
    return sorted(_handlers)


def enqueue(kind, payload=None, *, run_after=None):
    """
    Add a job to the queue and return it. `payload` is what its function will
    be given, as named values. The row is written in the caller's transaction.
    An unknown kind is a mistake in the code and raises at once, here, rather
    than failing later in the worker.
    """
    if kind not in _handlers:
        raise UnknownKind(f"No job handler is registered for {kind!r}.")
    return Job.objects.create(
        kind=kind, payload=payload or {}, run_after=run_after or timezone.now()
    )


def send_test_error():
    """
    Queue the job that fails once in the worker, and return it. The page that
    calls this then raises DeliberateError itself, so that one press sends an
    error from the web site and one from the worker.
    """
    return enqueue(TEST_ERROR_KIND, {"token": secrets.token_hex(8)})


def wait_after(attempts):
    """How long a job that has failed this many times waits before the next try."""
    return timedelta(minutes=2**attempts)


def run_one(now=None):
    """
    Do the oldest job that is due, if there is one. Returns True if a job was
    run (whether it worked or not), False if nothing was due.
    """
    now = now or timezone.now()
    with transaction.atomic():
        claimed = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(status=Job.Status.QUEUED, run_after__lte=now)
            .order_by("run_after", "id")
            .first()
        )
        if claimed is None:
            return False
        claimed.status = Job.Status.RUNNING
        claimed.locked_at = now
        claimed.attempts += 1
        claimed.save(update_fields=["status", "locked_at", "attempts"])
    # The claim is committed, so nobody else will take this job. Now do it, in
    # a transaction of its own: if it fails, what it wrote is undone.
    try:
        handler = _handlers.get(claimed.kind)
        if handler is None:
            raise UnknownKind
        with transaction.atomic():
            handler(**claimed.payload)
    except Exception as error:  # noqa: BLE001  (whatever went wrong, the worker carries on)
        _record_failure(claimed, error)
    else:
        Job.objects.filter(pk=claimed.pk).update(
            status=Job.Status.DONE, finished_at=timezone.now(), locked_at=None, last_error=""
        )
    return True


def _record_failure(claimed, error):
    """Put a failed job back for later, or mark it failed for good after its last try."""
    kind_of_error = type(error).__name__
    # Trying again cannot help a job nobody knows how to do.
    final = claimed.attempts >= claimed.max_attempts or isinstance(error, UnknownKind)
    # The kind of error only: its message may quote someone's address.
    logger.error(
        "Job %s (%s) failed on try %s of %s: %s%s",
        claimed.pk,
        claimed.kind,
        claimed.attempts,
        claimed.max_attempts,
        kind_of_error,
        "; giving up" if final else "",
    )
    changes = {"locked_at": None, "last_error": kind_of_error[:200]}
    if final:
        changes |= {"status": Job.Status.FAILED, "finished_at": timezone.now()}
    else:
        changes |= {
            "status": Job.Status.QUEUED,
            "run_after": timezone.now() + wait_after(claimed.attempts),
        }
    Job.objects.filter(pk=claimed.pk).update(**changes)


def run_due(now=None, limit=1000):
    """Do every job that is due, oldest first. Returns how many were run."""
    count = 0
    while count < limit and run_one(now):
        count += 1
    return count


def requeue_stuck(now=None):
    """
    Put back any job that has been "running" for too long: the worker doing it
    died. It will run again, which every handler must be able to bear. Returns
    how many were put back.
    """
    now = now or timezone.now()
    return Job.objects.filter(status=Job.Status.RUNNING, locked_at__lt=now - STUCK_AFTER).update(
        status=Job.Status.QUEUED, locked_at=None
    )


def retry(failed):
    """Staff ask for a failed job to be run again: back in the queue with a fresh count."""
    return Job.objects.filter(pk=failed.pk, status=Job.Status.FAILED).update(
        status=Job.Status.QUEUED,
        attempts=0,
        run_after=timezone.now(),
        finished_at=None,
        locked_at=None,
    )


def waiting(now=None):
    """
    How the queue stands, for the admin and /health/worker: {"count": jobs that
    are due and not started, "oldest": how long the oldest of them has been due
    (a timedelta, or None), "behind": True if that is too long}.
    """
    now = now or timezone.now()
    due = Job.objects.filter(status=Job.Status.QUEUED, run_after__lte=now)
    first = due.order_by("run_after").values_list("run_after", flat=True).first()
    oldest = now - first if first is not None else None
    return {
        "count": due.count(),
        "oldest": oldest,
        "behind": oldest is not None and oldest > BEHIND_AFTER,
    }
