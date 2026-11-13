"""
Queue the algorithm again for every submitted survey.

For when the algorithm has changed and older surveys should be worked out with
the new version. It only adds jobs to the queue; the background worker does
them, and the Background jobs page of the Django admin shows them going
through. Until there is an algorithm, the jobs it queues store nothing.

    python manage.py recompute_results

Running it twice queues everything twice, which is harmless: working a result
out again with the same version replaces the earlier one.
"""

from django.core.management.base import BaseCommand

from apps.jobs import services as jobs
from apps.responses.models import Response
from apps.results import services as results


class Command(BaseCommand):
    help = "Queue the algorithm again for every submitted survey."

    def handle(self, *args, **options):
        submitted = Response.objects.filter(status=Response.Status.SUBMITTED)
        queued = 0
        for number in submitted.values_list("pk", flat=True).iterator():
            jobs.enqueue(results.COMPUTE_RESULT, {"response_id": number})
            queued += 1
        self.stdout.write(f"Queued {queued} submitted survey(s) to be worked out again.")
