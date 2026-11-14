"""
A limit on guessing join codes (Milestone 7).

A join code lets anyone who holds it into an organization, so it must not be
found by trying many. A code is only ever checked for someone who is logged
in, so every guess belongs to an account, and the limit is per account: after
ten codes that were refused within an hour, the account is asked to wait until
the hour is up, and no code it types is looked at meanwhile.

Ten an hour is far more than someone mistyping their own code needs, and far
too few to find one: a code has ten characters.

The count lives in the site's cache (a database table, config/settings), not
in a model: it is nobody's data, it forgets itself after the hour, and staff
never need to look at it or reset it.

There is deliberately no limit by the visitor's address. The site sits behind
Caddy, and a mistake in reading the real address there would count every
visitor as one and lock them all out together.

An invite link is not limited here: its secret is much longer, and it only
works for the account that has verified the invited address.
"""

import time

from django.core.cache import cache

LIMIT = 10
WINDOW = 60 * 60  # seconds
MESSAGE = (
    "Too many codes that did not work. Please wait an hour and try again, or ask the "
    "organization for a new code or an invite."
)


def _now():
    return time.time()


def _key(account):
    return f"join-code-refused:{account.pk}"


def _refusals(account):
    """This account's count for the hour it is in: {"count", "until"}, or None if none is running."""
    state = cache.get(_key(account))
    if state is None or state["until"] <= _now():
        return None
    return state


def blocked(account):
    """True if this account has had its ten refusals for the hour."""
    state = _refusals(account)
    return state is not None and state["count"] >= LIMIT


def note_refusal(account):
    """Count one refused code. The hour starts with the first."""
    now = _now()
    state = _refusals(account) or {"count": 0, "until": now + WINDOW}
    state["count"] += 1
    cache.set(_key(account), state, timeout=max(1, int(state["until"] - now)))
