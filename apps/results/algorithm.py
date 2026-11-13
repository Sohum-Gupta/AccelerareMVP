"""
The algorithm. There is none yet.

This file is the one place it will live. `compute_result` is given a submitted
response and returns everything it worked out as a plain dictionary, or None
for "nothing to store". Today it always returns None, so no result is ever
stored and the result page says results are being prepared.

When the algorithm arrives: write it here, raise ALGORITHM_VERSION, and fill
the tier map in tiering.py. Nothing else in the site needs to change. To work
out older surveys again, run `manage.py recompute_results`.

It must be safe to run twice on the same response and give the same answer:
the worker may run a job more than once.
"""

# Raise this whenever the algorithm changes, so old and new results can be told apart.
ALGORITHM_VERSION = "0.0.0"


def compute_result(response):
    """Everything the algorithm works out from this response, or None. Nothing, for now."""
    return None  # noqa: RET501  (said out loud on purpose: this is the whole algorithm today)
