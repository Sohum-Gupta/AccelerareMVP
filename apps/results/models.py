"""
Results: what the algorithm worked out from one submitted survey.

There is no algorithm yet (algorithm.py returns nothing), so this table is
empty. It exists so that the algorithm, when it comes, has somewhere to put
its output and nothing else has to change.

One row is one run of one version of the algorithm on one response. The
payload is everything the algorithm produced, in full; what a person is shown
is filtered by the tier of their licence when the page is drawn (tiering.py),
so upgrading a licence shows more without working anything out again.

All writes go through services.py.
"""

from django.db import models


class Result(models.Model):
    # CASCADE: a result is about one response and goes when the response does.
    response = models.ForeignKey(
        "responses.Response", on_delete=models.CASCADE, related_name="results"
    )
    # Which version of the algorithm produced it (algorithm.ALGORITHM_VERSION).
    algorithm_version = models.CharField(max_length=20)
    payload = models.JSONField()
    computed_at = models.DateTimeField()

    class Meta:
        ordering = ["-computed_at", "-id"]
        constraints = [
            # Working the same response out again with the same version
            # replaces the row; it never adds a second.
            models.UniqueConstraint(
                fields=["response", "algorithm_version"], name="result_one_per_response_version"
            ),
        ]

    def __str__(self):
        return f"Result of response {self.response_id} (algorithm {self.algorithm_version})"
