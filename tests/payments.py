"""
Helpers for the payment tests. Not a test file.

FakeStripe stands in for apps.payments.stripe_api: it remembers the payment
pages the site opened, can be told that one was paid, and answers the way the
real file does, with plain values. No test talks to Stripe (tests/conftest.py).
"""

import hashlib
import hmac
import json
import time

from apps.payments import stripe_api
from apps.payments.models import Price

SECRET = "whsec_made_up_for_tests"


class FakeStripe:
    def __init__(self):
        self.pages = {}  # session id -> {"asked": what create_checkout was given, "paid": bool}
        self.refunds = []  # what refund_payment was given, in order
        self.fail = None  # set to an exception to make the next calls fail

    # --- what the site calls ---

    def create_checkout(self, **asked):
        if self.fail:
            raise self.fail
        session_id = f"cs_test_{len(self.pages) + 1}"
        self.pages[session_id] = {"asked": asked, "paid": False, "charged": None}
        return {**self.get_checkout(session_id), "url": f"https://stripe.test/pay/{session_id}"}

    def get_checkout(self, session_id):
        if self.fail:
            raise self.fail
        page = self.pages[session_id]
        asked = page["asked"]
        amount = asked["unit_amount_cents"] * asked["quantity"]
        return {
            "id": session_id,
            "url": "",
            "paid": page["paid"],
            "payment_intent": f"pi_{session_id}" if page["paid"] else "",
            "invoice": f"in_{session_id}" if page["paid"] and asked["invoice"] else "",
            "amount_cents": amount if page["charged"] is None else page["charged"],
            "currency": asked["currency"],
        }

    def refund_payment(self, payment_intent, amount_cents, *, key, reference):
        if self.fail:
            raise self.fail
        self.refunds.append(
            {"payment_intent": payment_intent, "amount_cents": amount_cents, "key": key}
        )
        return f"re_test_{len(self.refunds)}"

    # --- what a test does ---

    @property
    def last(self):
        """The id of the payment page opened most recently."""
        return list(self.pages)[-1]

    def asked(self, session_id=None):
        return self.pages[session_id or self.last]["asked"]

    def pay(self, session_id=None, charged=None):
        """The person paid on Stripe's page. Returns what Stripe would now say about it."""
        session_id = session_id or self.last
        self.pages[session_id]["paid"] = True
        self.pages[session_id]["charged"] = charged
        return self.get_checkout(session_id)


def starting_prices():
    """
    The three prices the migration creates. A threaded test empties every table
    when it ends, and what a migration wrote is not put back, so a test that
    runs after one finds no prices unless it asks for them here.
    """
    for tier, cents in {1: 100, 2: 200, 3: 300}.items():
        Price.objects.get_or_create(tier=tier, defaults={"amount_cents": cents})


def install(monkeypatch, settings):
    """Give the site a made-up key and a FakeStripe in place of the real file's calls."""
    starting_prices()
    settings.STRIPE_SECRET_KEY = "sk_test_made_up"
    settings.STRIPE_WEBHOOK_SECRET = SECRET
    fake = FakeStripe()
    for name in ("create_checkout", "get_checkout", "refund_payment"):
        monkeypatch.setattr(stripe_api, name, getattr(fake, name))
    return fake


def signed(payload, secret=SECRET, at=None):
    """The Stripe-Signature header Stripe would send with this body."""
    at = int(at or time.time())
    digest = hmac.new(secret.encode(), f"{at}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={at},v1={digest}"


def paid_message(checkout):
    """The body of Stripe's "this payment page was paid" message for a FakeStripe page."""
    found = {
        "id": checkout["id"],
        "object": "checkout.session",
        "payment_status": "paid" if checkout["paid"] else "unpaid",
        "payment_intent": checkout["payment_intent"] or None,
        "invoice": checkout["invoice"] or None,
        "amount_subtotal": checkout["amount_cents"],
        "amount_total": checkout["amount_cents"],
        "currency": checkout["currency"],
    }
    return json.dumps(
        {"id": "evt_test_1", "type": "checkout.session.completed", "data": {"object": found}}
    )


def post_webhook(client, payload, signature=None):
    """Send a body to the webhook as Stripe would."""
    return client.post(
        "/payments/stripe/webhook/",
        data=payload,
        content_type="application/json",
        headers={"Stripe-Signature": signed(payload) if signature is None else signature},
    )
