"""
The background job the responses app knows how to do (see apps/jobs).

Working out a result. The job is queued when a survey is submitted, with the
response's number. The algorithm and the table its output goes in belong to
the results app; the job lives here because this app knows what a response is.

There is no algorithm yet, so today this job stores nothing. It still runs for
every submission, which proves the path from "submitted" to "worked out"
before anything depends on it.
"""

from apps.jobs import services as jobs
from apps.results import services as results

from .models import Response


@jobs.job(results.COMPUTE_RESULT)
def compute_result(response_id):
    """
    Work out and store the result of one submitted response. Does nothing for
    a response that has gone or is not submitted. Safe to run twice: the same
    version of the algorithm replaces its own earlier row.
    """
    response = Response.objects.filter(pk=response_id, status=Response.Status.SUBMITTED).first()
    if response is not None:
        results.compute_and_store(response)
