"""
Every write of a result goes through here.

This app imports no other app. It is handed a response by the responses app
(which owns the background job that works a result out, because it knows what
a response is) and stores what the algorithm returns.
"""

from django.utils import timezone

from . import algorithm, tiering
from .models import Result

# The background job that works out a result (see responses/job_handlers.py).
COMPUTE_RESULT = "compute_result"


def compute_and_store(response):
    """
    Run the algorithm on a submitted response and store what it returns.
    Returns the Result, or None when the algorithm returned nothing (as it
    always does until there is one). Run again with the same version, it
    replaces the earlier row.
    """
    payload = algorithm.compute_result(response)
    if payload is None:
        return None
    result, _ = Result.objects.update_or_create(
        response=response,
        algorithm_version=algorithm.ALGORITHM_VERSION,
        defaults={"payload": payload, "computed_at": timezone.now()},
    )
    return result


def latest_for(response):
    """The most recently worked-out result of this response, or None."""
    return Result.objects.filter(response=response).order_by("-computed_at", "-id").first()


def visible_result(response, tier):
    """What a person whose licence is at this tier may see of the latest result, or None."""
    result = latest_for(response)
    if result is None:
        return None
    return tiering.visible_fields(result.payload, tier)
