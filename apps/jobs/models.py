"""
The queue of background jobs: work to be done later, outside a web request.

A Job is one piece of work waiting to be done, being done, done or failed. The
web pages only add rows here (services.enqueue); one separate process, the
worker (`manage.py run_worker`), reads them and does the work. So a slow or
failing mail server can never make a page slow or make it fail.

A job's payload holds plain numbers and words only, never a name, an email
address or an answer: for an email it holds the number of the licence, and the
address is looked up when the job runs. That keeps this table free of personal
data, so erasing a person never has to search it.

This app imports no other app. An app that wants something done later calls
services.enqueue with a kind; the function that does it lives in that app's
job_handlers.py.

All writes go through services.py; the models only describe the shape.
"""

from django.db import models
from django.utils import timezone


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    # Which function does it (see services.job). For example "send_licence_email".
    kind = models.CharField(max_length=50)
    # What that function is given. Plain values only; never personal data.
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.QUEUED)
    # How many times it has been tried, and how many times it may be.
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    # Not before this moment. A job that failed is put back with a later time.
    run_after = models.DateTimeField(default=timezone.now)
    # When the worker picked it up; emptied when it finishes.
    locked_at = models.DateTimeField(null=True, blank=True)
    # The kind of error only ("SMTPServerDisconnected"), never its message:
    # a mail server's reply can quote an address.
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "background job"
        indexes = [models.Index(fields=["status", "run_after"], name="job_status_run_after")]

    def __str__(self):
        return f"Job {self.pk} ({self.kind})"
