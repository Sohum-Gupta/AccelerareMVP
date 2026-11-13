"""
Every write to prices and payments goes through here.

Buying is three steps, and the money moves in the middle one, on Stripe's site:

1. start_personal, start_upgrade or start_stock check the rules, write a
   Purchase row ("pending") with the price the server read, open a payment page
   at Stripe for exactly that amount, and return its address. The page that
   called sends the person there. Nothing the browser sent is trusted beyond a
   tier and a number.
2. The person pays on Stripe's page. This site never sees the card.
3. fulfil gives what was paid for: a personal licence, a higher tier, or
   licences in an organization's stock. It is called from two places, the page
   the person comes back to and the message Stripe sends us, because either can
   fail to arrive. It locks the Purchase row and does nothing unless the row is
   still pending, so however often and in whatever order it is called, what
   was paid for is given exactly once.

When money has come in and the site cannot finish its side (the account was
erased while paying, the licence changed under an upgrade), nothing is given,
the row is marked "needs attention" with the reason in plain words, and staff
refund it from the admin.

Lock order: the Purchase row first, then whatever it gives (the organization,
or the licence). Nothing else locks a Purchase.

A refused action raises Refused (the organization pages' own), whose message is
plain words for the page; NotFound when the licence is not the person's own.
"""

import logging

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement

from . import stripe_api
from .models import MIN_PRICE_CENTS, Price, Purchase

logger = logging.getLogger(__name__)

TIERS = (1, 2, 3)
CURRENCY = "usd"
# The most licences an organization can buy in one purchase.
MAX_STOCK_PER_PURCHASE = 1000

# The plain-words refusal the pages already catch and show.
Refused = orgs.Refused


class NotFound(Refused):
    """The licence is not this person's own. A page answers "not found"."""


NOT_OPEN = "Buying online is not open yet. Contact Accelerare to buy a licence."
COULD_NOT_START = (
    "We could not open the payment page just now, so nothing was charged. "
    "Please try again in a moment."
)
CHOOSE_A_TIER = "Choose Tier 1, 2 or 3."


# --- reads ----------------------------------------------------------------------------


def is_open():
    """True if things can be bought: the site has a Stripe key."""
    return stripe_api.is_open()


def prices():
    """What one licence of each tier costs today: {tier: cents}."""
    return dict(Price.objects.values_list("tier", "amount_cents"))


def dollars(cents):
    """An amount as people read it: 250 is "$2.50"."""
    return f"${cents // 100:,}.{cents % 100:02d}"


def upgrades_for(entitlement):
    """
    {tier: what moving this licence up to it costs, in cents}: the difference
    between the two prices today. Only tiers above the licence's own, and only
    where the difference is something Stripe can charge. Empty for a licence
    that cannot be upgraded by paying: one held through an organization, or
    one that has been withdrawn.
    """
    if not entitlement.is_personal or not entitlement.is_active:
        return {}
    price = prices()
    costs = {
        tier: price[tier] - price[entitlement.tier]
        for tier in TIERS
        if tier > entitlement.tier and tier in price and entitlement.tier in price
    }
    return {tier: cents for tier, cents in costs.items() if cents >= MIN_PRICE_CENTS}


# --- starting a purchase ----------------------------------------------------------------


def start_personal(account, tier, *, request):
    """
    A person buys one personal licence of this tier. Returns the address of
    Stripe's payment page to send them to.
    """
    _check_can_buy(account)
    cents = _price_of(tier)
    purchase = Purchase.objects.create(
        kind=Purchase.Kind.PERSONAL,
        buyer=account,
        tier=tier,
        unit_amount_cents=cents,
        amount_cents=cents,
        currency=CURRENCY,
    )
    return _open_payment_page(purchase, f"Tier {tier} licence", account, request)


def start_upgrade(account, entitlement, tier, *, request):
    """
    A person pays to raise one of their own personal licences to a higher tier,
    for the difference between the two prices. Returns the address of Stripe's
    payment page. NotFound for a licence that is not theirs.
    """
    _check_can_buy(account)
    _check_tier(tier)
    licence = Entitlement.objects.filter(
        pk=entitlement.pk, person_id=account.person_id, person__isnull=False
    ).first()
    if licence is None:
        raise NotFound("That licence was not found.")
    if not licence.is_active:
        raise Refused("That licence has been withdrawn, so it cannot be upgraded.")
    if tier <= licence.tier:
        raise Refused(f"That licence is already Tier {licence.tier}. Choose a higher tier.")
    cents = upgrades_for(licence).get(tier)
    if cents is None:
        raise Refused("That upgrade is not available at the moment.")
    purchase = Purchase.objects.create(
        kind=Purchase.Kind.UPGRADE,
        buyer=account,
        entitlement=licence,
        tier=tier,
        from_tier=licence.tier,
        unit_amount_cents=cents,
        amount_cents=cents,
        currency=CURRENCY,
    )
    description = f"Upgrade from Tier {licence.tier} to Tier {tier}"
    return _open_payment_page(purchase, description, account, request)


def start_stock(admin_membership, tier, quantity, *, request):
    """
    An organization's admin buys `quantity` licences of one tier for its stock.
    Returns the address of Stripe's payment page. Any active admin may buy.
    """
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise Refused("Enter how many licences to buy, as a whole number.")
    if not 1 <= quantity <= MAX_STOCK_PER_PURCHASE:
        raise Refused(f"Buy from 1 to {MAX_STOCK_PER_PURCHASE:,} licences at a time.")
    cents = _price_of(tier)
    with transaction.atomic():
        # Read again, not trusted: they may have been demoted since the page loaded.
        enterprise, admin = orgs.lock_for_admin(admin_membership)
        account = admin.account
        _check_can_buy(account)
        if orgs.seats_bought(enterprise)[tier] + quantity > orgs.MAX_SEATS:
            raise Refused(
                f"An organization can hold at most {orgs.MAX_SEATS:,} licences of a tier."
            )
        purchase = Purchase.objects.create(
            kind=Purchase.Kind.STOCK,
            buyer=account,
            enterprise=enterprise,
            tier=tier,
            quantity=quantity,
            unit_amount_cents=cents,
            amount_cents=cents * quantity,
            currency=CURRENCY,
        )
    description = f"Tier {tier} licence for {enterprise.name}"
    return _open_payment_page(purchase, description, account, request, invoice=True)


def _check_can_buy(account):
    if not is_open():
        raise Refused(NOT_OPEN)
    if not account.is_active or account.anonymised_at is not None:
        raise Refused("This account cannot buy a licence.")
    if not accounts.has_verified_email(account):
        raise Refused("Verify your email address before buying.")


def _check_tier(tier):
    # bool is an int in Python, and 2.0 == 2: neither may pass as a tier.
    if isinstance(tier, bool) or not isinstance(tier, int) or tier not in TIERS:
        raise Refused(CHOOSE_A_TIER)


def _price_of(tier):
    _check_tier(tier)
    cents = prices().get(tier)
    if cents is None:
        raise Refused("That tier has no price at the moment.")
    return cents


def _open_payment_page(purchase, description, account, request, *, invoice=False):
    """
    Open Stripe's payment page for a purchase that has just been written, and
    return its address. The row is committed before Stripe is called, so when
    Stripe later says "paid" there is always a row to find. If the page cannot
    be opened, the row is marked failed and the person is asked to try again:
    nothing was charged.
    """
    done = request.build_absolute_uri(reverse("payments:done"))
    cancelled = request.build_absolute_uri(reverse("payments:cancelled"))
    try:
        page = stripe_api.create_checkout(
            reference=purchase.pk,
            description=description,
            unit_amount_cents=purchase.unit_amount_cents,
            quantity=purchase.quantity,
            currency=purchase.currency,
            # Fills in the address on Stripe's page, where Stripe sends the receipt.
            email=account.email,
            # Stripe puts its own id where the braces are when it sends them back.
            success_url=done + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=f"{cancelled}?purchase={purchase.pk}",
            invoice=invoice,
        )
    except (stripe_api.StripeFailed, stripe_api.NotConfigured) as error:
        Purchase.objects.filter(pk=purchase.pk).update(status=Purchase.Status.FAILED)
        logger.error("Could not open a payment page for payment %s (%s)", purchase.pk, error)
        raise Refused(COULD_NOT_START) from None
    Purchase.objects.filter(pk=purchase.pk).update(stripe_session_id=page["id"])
    return page["url"]


# --- giving what was paid for -------------------------------------------------------------


def fulfil(checkout):
    """
    Stripe says something about a payment page (`checkout`, the plain values
    from stripe_api): if it is one of ours, is paid, and has not been dealt
    with yet, give what it was for. Returns the Purchase, or None if we never
    opened that page.

    Safe to call any number of times, from the page the person returns to and
    from Stripe's message, in any order: only a row that is still pending is
    acted on, and the row is locked while it is.
    """
    with transaction.atomic():
        purchase = (
            Purchase.objects.select_for_update().filter(stripe_session_id=checkout["id"]).first()
        )
        if purchase is None or not checkout["id"]:
            return None
        if purchase.status != Purchase.Status.PENDING or not checkout["paid"]:
            return purchase
        purchase.status = Purchase.Status.PAID
        purchase.paid_at = timezone.now()
        purchase.stripe_payment_intent_id = checkout["payment_intent"]
        purchase.stripe_invoice_id = checkout["invoice"]
        charged = (checkout["amount_cents"], checkout["currency"])
        if charged != (purchase.amount_cents, purchase.currency):
            _needs_attention(
                purchase,
                "Stripe took a different amount from the one on this record, so nothing was "
                "given. Look at the payment in Stripe's dashboard and refund it.",
            )
        else:
            try:
                # Its own savepoint: if giving fails half way, what it wrote is
                # undone and the row still records that the money came in.
                with transaction.atomic():
                    _give(purchase)
            except Refused as error:
                _needs_attention(purchase, f"Paid, but nothing was given: {error} Refund it.")
        purchase.save()
        return purchase


def _give(purchase):
    """Give what the purchase was for. The caller holds the row's lock. Refused if it cannot."""
    if purchase.kind == Purchase.Kind.STOCK:
        orgs.add_seats(purchase.enterprise, purchase.tier, purchase.quantity)
        return
    buyer = purchase.buyer
    if buyer is None or not buyer.is_active or buyer.anonymised_at is not None:
        raise Refused("the account that paid no longer exists.")
    if purchase.kind == Purchase.Kind.PERSONAL:
        purchase.entitlement = licences.grant_individual(
            buyer.person, purchase.tier, Entitlement.Source.PURCHASE
        )
        return
    licence = Entitlement.objects.select_for_update().filter(pk=purchase.entitlement_id).first()
    if licence is None or not licence.is_active:
        raise Refused("the licence it was for has been withdrawn.")
    if licence.tier != purchase.from_tier:
        raise Refused(
            f"the licence was Tier {licence.tier}, not Tier {purchase.from_tier}, "
            "by the time the payment arrived."
        )
    licences.change_tier(licence, purchase.tier)


def _needs_attention(purchase, note):
    """Mark a payment for staff, and tell them (the log line reaches Sentry and names nobody)."""
    purchase.needs_attention = True
    purchase.note = note
    logger.error("Payment %s needs attention: %s", purchase.pk, note)
