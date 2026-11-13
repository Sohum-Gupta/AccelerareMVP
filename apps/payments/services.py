"""
Every write to prices and payments goes through here.

So far: reading the prices. Starting a purchase, giving what was paid for and
refunding arrive with the pages that use them (Milestone 4b, PRs 2 and 4).

A refused action raises Refused, whose message is plain words for the page.
"""

from .models import Price

TIERS = (1, 2, 3)
CURRENCY = "usd"


class Refused(Exception):
    """An action the rules do not allow. str(error) is plain words for the person."""


def prices():
    """What one licence of each tier costs today: {tier: cents}."""
    return dict(Price.objects.values_list("tier", "amount_cents"))


def dollars(cents):
    """An amount as people read it: 250 is "$2.50"."""
    return f"${cents // 100:,}.{cents % 100:02d}"
