"""
The only file that talks to Stripe.

Everything else in the app, and every test, sees Stripe through the four
functions here: open a payment page, ask about one, send money back, and read
a message Stripe sent us. Each returns plain values (text, numbers, a small
dict), never one of the library's own objects, so nothing else needs to know
how Stripe's library is shaped.

Stripe's hosted payment page ("Checkout") is used: the person pays on Stripe's
site and comes back. A card number never reaches this site.

Two settings, both optional. Without STRIPE_SECRET_KEY nothing can be bought
(`is_open` is False and the calls raise NotConfigured). Without
STRIPE_WEBHOOK_SECRET Stripe's messages cannot be checked, so `read_event`
raises NotConfigured.

Nothing here writes a log line: what passes through holds an email address.
"""

import json

import stripe
from django.conf import settings

# How long to wait for Stripe before giving up, in seconds. The web server
# stops a request that takes 30, so this must be well under it.
TIMEOUT_SECONDS = 10


class NotConfigured(Exception):
    """The Stripe key (or, for messages, the webhook secret) is not set."""


class StripeFailed(Exception):
    """Stripe could not be reached or refused. str(error) is safe to log: it names no one."""


class BadSignature(Exception):
    """A message that claims to be from Stripe and is not signed with our secret."""


def is_open():
    """True if the site has a Stripe key, so things can be bought."""
    return bool(settings.STRIPE_SECRET_KEY)


def _client():
    if not settings.STRIPE_SECRET_KEY:
        raise NotConfigured("STRIPE_SECRET_KEY is not set.")
    return stripe.StripeClient(
        settings.STRIPE_SECRET_KEY,
        max_network_retries=1,
        http_client=stripe.RequestsClient(timeout=TIMEOUT_SECONDS),
    )


def _failed(error):
    # The class and Stripe's short code only. The message can quote what was sent.
    code = getattr(error, "code", None) or "no code"
    return StripeFailed(f"{type(error).__name__} ({code})")


def _checkout(found):
    """A payment page as plain values, whether Stripe returned it or sent it in a message."""
    intent = found.get("payment_intent") or ""
    if isinstance(intent, dict):
        intent = intent.get("id", "")
    invoice = found.get("invoice") or ""
    if isinstance(invoice, dict):
        invoice = invoice.get("id", "")
    return {
        "id": found.get("id", ""),
        "url": found.get("url") or "",
        "paid": found.get("payment_status") == "paid",
        "payment_intent": intent,
        "invoice": invoice,
        # Before tax: what our own row says was charged.
        "amount_cents": found.get("amount_subtotal"),
        "currency": (found.get("currency") or "").lower(),
    }


def create_checkout(
    *,
    reference,
    description,
    unit_amount_cents,
    quantity,
    currency,
    email,
    success_url,
    cancel_url,
    invoice=False,
):
    """
    Open a payment page and return it ({"id", "url", ...}): send the person to
    its "url". `reference` is our own purchase's id, which Stripe hands back.
    `email` fills in the address on Stripe's page, where the receipt goes.
    With `invoice`, Stripe also makes a numbered invoice (an organization's
    purchase).
    """
    price = {
        "currency": currency,
        "unit_amount": unit_amount_cents,
        "product_data": {"name": description},
    }
    params = {
        "mode": "payment",
        "line_items": [{"quantity": quantity, "price_data": price}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(reference),
        "metadata": {"purchase": str(reference)},
        "payment_intent_data": {"metadata": {"purchase": str(reference)}},
        "customer_email": email,
    }
    if settings.STRIPE_AUTOMATIC_TAX:
        # Stripe works out and adds sales tax. Needs tax set up in Stripe's dashboard.
        price["tax_behavior"] = "exclusive"
        params["automatic_tax"] = {"enabled": True}
    if invoice:
        params["invoice_creation"] = {
            "enabled": True,
            "invoice_data": {"description": description, "metadata": {"purchase": str(reference)}},
        }
    client = _client()
    try:
        session = client.v1.checkout.sessions.create(params=params)
    except stripe.StripeError as error:
        raise _failed(error) from None
    return _checkout(session.to_dict())


def get_checkout(session_id):
    """Ask Stripe about a payment page we opened: has it been paid, and how much."""
    client = _client()
    try:
        session = client.v1.checkout.sessions.retrieve(session_id)
    except stripe.StripeError as error:
        raise _failed(error) from None
    return _checkout(session.to_dict())


def refund_payment(payment_intent, amount_cents, *, key, reference):
    """
    Send money back for a payment, and return Stripe's id for the refund.
    `key` makes a repeated request the same refund, not a second one.
    """
    client = _client()
    try:
        refund = client.v1.refunds.create(
            params={
                "payment_intent": payment_intent,
                "amount": amount_cents,
                "metadata": {"purchase": str(reference)},
            },
            options={"idempotency_key": key},
        )
    except stripe.StripeError as error:
        raise _failed(error) from None
    return refund.to_dict().get("id", "")


def read_event(payload, signature):
    """
    Check that a message really came from Stripe, and return it as plain values:
    {"type": "checkout.session.completed", "object": {...}}. `payload` is the
    request's body exactly as it arrived. Raises BadSignature for anything not
    signed with our secret, which includes a message altered on the way and
    one replayed long after it was sent.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise NotConfigured("STRIPE_WEBHOOK_SECRET is not set.")
    try:
        stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
        event = json.loads(payload)
    except (stripe.SignatureVerificationError, ValueError, TypeError):
        raise BadSignature("The message is not signed with our secret.") from None
    found = (event.get("data") or {}).get("object") or {}
    return {"type": event.get("type", ""), "object": found}


def checkout_in(event):
    """The payment page a "checkout.session.completed" message is about, as plain values."""
    return _checkout(event["object"])


def charge_in(event):
    """The charge a "charge.refunded" message is about: which payment, and how much has gone back."""
    found = event["object"]
    intent = found.get("payment_intent") or ""
    if isinstance(intent, dict):
        intent = intent.get("id", "")
    return {
        "payment_intent": intent,
        "amount_cents": found.get("amount"),
        "refunded_cents": found.get("amount_refunded") or 0,
    }
