"""
Shared by every test.

No test may talk to Stripe's servers. The settings used for tests blank the
Stripe keys (config/settings/test.py), and the fixture below is the second
lock: it replaces the library's client, so even a test that sets a made-up key
and forgets to fake `apps.payments.stripe_api` fails loudly instead of sending
a request across the internet. A test of stripe_api itself puts its own fake
client in its place.
"""

import pytest
import stripe


class NoStripeInTests:
    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "A test tried to reach Stripe. Fake apps.payments.stripe_api, or the client, instead."
        )


@pytest.fixture(autouse=True)
def no_real_stripe(monkeypatch):
    monkeypatch.setattr(stripe, "StripeClient", NoStripeInTests)
