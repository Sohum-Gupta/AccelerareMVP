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

Refunding (the founder's rules of 2026-11-13) is one step for staff: `refund`
takes back what was sold and sends the money back through Stripe, together or
not at all. Only for a licence that has not been used, within 30 days of the
payment; for an organization, only licences still in its stock. A refund made
in Stripe's own dashboard instead is noticed when Stripe tells us
(`record_outside_refund`): what was sold is taken back if those rules allow,
and otherwise the payment is marked "needs attention" and nothing is taken
from anyone.

Lock order: the Purchase row first, then whatever it gives or takes back (the
organization, or the licence). Nothing else locks a Purchase.

A refused action raises Refused (the organization pages' own), whose message is
plain words for the page; NotFound when the licence is not the person's own.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement

from . import stripe_api
from .models import MIN_PRICE_CENTS, Price, Purchase, Refund

logger = logging.getLogger(__name__)

TIERS = (1, 2, 3)
CURRENCY = "usd"
# The most licences an organization can buy in one purchase.
MAX_STOCK_PER_PURCHASE = 1000
# How long after the payment staff can refund from the admin.
REFUND_DAYS = 30

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
                purchase.given_at = purchase.paid_at
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


# --- refunds ----------------------------------------------------------------------------

STARTED = "The survey on this licence has been started, so it cannot be refunded."
UPGRADE_ON_TOP = "This licence has a paid upgrade on it. Refund the upgrade first."
STRIPE_REFUSED = (
    "Stripe did not make the refund, so nothing was changed. Try again in a moment; "
    "if it keeps failing, look at the payment in Stripe's dashboard."
)


def refund_preview(purchase):
    """
    What the Refund button would do to this payment, for the page that asks
    first: {"can": bool, "why_not": words, "most": how many licences could go
    back (1 unless it is a stock purchase), "unit": cents each, "gives_back":
    what will be taken back, in words}. Nothing is locked or changed; `refund`
    checks everything again.
    """
    try:
        most = _refundable_quantity(purchase, None)
    except Refused as error:
        return {"can": False, "why_not": str(error), "most": 0, "unit": 0, "gives_back": ""}
    reason, gives_back = "", _what_goes_back(purchase)
    if purchase.given_at is not None:
        try:
            # A dry run inside a transaction that is always undone.
            with transaction.atomic():
                _take_back(purchase, 1 if purchase.kind == Purchase.Kind.STOCK else most)
                transaction.set_rollback(True)
        except Refused as error:
            reason = str(error)
    if purchase.kind == Purchase.Kind.STOCK and purchase.given_at is not None and not reason:
        left = next(
            line["left"]
            for line in orgs.seat_summary(purchase.enterprise)
            if line["tier"] == purchase.tier
        )
        most = min(most, left)
    return {
        "can": not reason,
        "why_not": reason,
        "most": most,
        "unit": purchase.unit_amount_cents,
        "gives_back": gives_back,
    }


def refund(purchase, by, quantity=None):
    """
    Staff refund a payment: take back what was sold and send the money back
    through Stripe, together or not at all. Returns the Refund.

    `quantity` is for a stock purchase: how many of its licences to refund (all
    that have not been refunded yet, if not given). A personal licence or an
    upgrade is refunded whole.

    Refused when the payment was never completed or is already refunded, when
    it is more than 30 days old, when the licence has been used or has a paid
    upgrade on top, when an organization no longer has that many in its stock,
    and when Stripe will not make the refund. A refusal changes nothing.
    """
    with transaction.atomic():
        purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
        quantity = _refundable_quantity(purchase, quantity)
        amount = purchase.unit_amount_cents * quantity
        if purchase.given_at is not None:
            _take_back(purchase, quantity)
        try:
            stripe_refund = stripe_api.refund_payment(
                purchase.stripe_payment_intent_id,
                amount,
                # The same request sent twice is one refund at Stripe, not two.
                key=f"refund-{purchase.pk}-after-{purchase.refunded_cents}",
                reference=purchase.pk,
            )
        except (stripe_api.StripeFailed, stripe_api.NotConfigured) as error:
            logger.error("Stripe refused the refund of payment %s (%s)", purchase.pk, error)
            # Raising inside the transaction undoes what was just taken back.
            raise Refused(STRIPE_REFUSED) from None
        made = Refund.objects.create(
            purchase=purchase,
            amount_cents=amount,
            quantity=quantity if purchase.given_at is not None else 0,
            stripe_refund_id=stripe_refund,
            made_by=by,
        )
        _record_refunded(purchase, amount, quantity)
        if purchase.status == Purchase.Status.REFUNDED:
            purchase.needs_attention = False  # the money has gone back: dealt with
        purchase.save()
        return made


def record_outside_refund(charge):
    """
    Stripe says money has gone back for a charge (`charge`: the plain values
    from stripe_api.charge_in). If it is more than this site has refunded, the
    refund was made in Stripe's own dashboard: record it, and take back what
    was sold if the rules allow. If they do not (the survey was started, the
    licences have been given out), the payment is marked for staff and nothing
    is taken from anyone. Returns the Purchase, or None if the charge is not
    one of ours. Safe to run twice: the second time there is nothing new.
    """
    if not charge["payment_intent"]:
        return None
    with transaction.atomic():
        purchase = (
            Purchase.objects.select_for_update()
            .filter(stripe_payment_intent_id=charge["payment_intent"])
            .first()
        )
        if purchase is None:
            return None
        extra = min(charge["refunded_cents"], purchase.amount_cents) - purchase.refunded_cents
        if extra <= 0:
            return purchase  # our own Refund button already recorded it
        whole, remainder = divmod(extra, purchase.unit_amount_cents)
        took, problem = 0, ""
        if purchase.given_at is None:
            pass  # nothing was ever given, so there is nothing to take back
        elif remainder or whole > purchase.quantity - purchase.refunded_quantity:
            problem = "the amount is not a whole number of licences, so nothing was taken back."
        else:
            try:
                with transaction.atomic():
                    _take_back(purchase, whole)
                took = whole
            except Refused as error:
                problem = f"nothing was taken back: {error}"
        Refund.objects.create(purchase=purchase, amount_cents=extra, quantity=took)
        _record_refunded(purchase, extra, took)
        if problem:
            _needs_attention(
                purchase,
                f"{dollars(extra)} was refunded in Stripe's dashboard, but {problem} "
                "Decide by hand what should happen to what was sold.",
            )
        elif purchase.status == Purchase.Status.REFUNDED:
            purchase.needs_attention = False
        purchase.save()
        return purchase


def _refundable_quantity(purchase, quantity):
    """How many licences of this payment a refund would cover, or Refused."""
    if purchase.status in (Purchase.Status.PENDING, Purchase.Status.FAILED):
        raise Refused("This payment was never completed, so there is nothing to refund.")
    if purchase.status == Purchase.Status.REFUNDED:
        raise Refused("This payment has already been refunded in full.")
    if not purchase.stripe_payment_intent_id:
        raise Refused("This payment has no reference at Stripe, so it cannot be refunded here.")
    # Money that came in for nothing can always go back; the 30 days are for
    # changing one's mind about something that was given.
    age = timezone.now() - (purchase.paid_at or timezone.now())
    if purchase.given_at is not None and age > timedelta(days=REFUND_DAYS):
        raise Refused(
            f"This payment is more than {REFUND_DAYS} days old, so it can no longer be refunded."
        )
    remaining = purchase.quantity - purchase.refunded_quantity
    if purchase.given_at is None:
        # Nothing was given: all the money that has not gone back yet, in one go.
        remaining = purchase.refundable_cents // purchase.unit_amount_cents
    if remaining < 1:
        raise Refused("There is nothing left of this payment to refund.")
    if quantity is None:
        return remaining
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise Refused("Enter how many licences to refund, as a whole number.")
    if quantity > remaining:
        raise Refused(f"Only {remaining:,} of this payment's licences can still be refunded.")
    if purchase.given_at is None and quantity != remaining:
        raise Refused("Nothing was given for this payment, so it is refunded whole.")
    return quantity


def _what_goes_back(purchase):
    """In words, what a refund takes back, for the page that asks first."""
    if purchase.given_at is None:
        return "Nothing was given for this payment, so nothing is taken back."
    if purchase.kind == Purchase.Kind.STOCK:
        return (
            f"The Tier {purchase.tier} licences refunded are taken out of the stock of "
            f"{purchase.enterprise.name}. Only licences still in the stock can be refunded."
        )
    if purchase.kind == Purchase.Kind.UPGRADE:
        return f"The licence goes back from Tier {purchase.tier} to Tier {purchase.from_tier}."
    return "The licence is withdrawn. It has not been used, so nothing else is lost."


def _take_back(purchase, quantity):
    """
    Take back what the purchase gave. The caller holds the row's lock and is
    inside a transaction. Refused if the founder's rules do not allow it.
    """
    if purchase.kind == Purchase.Kind.STOCK:
        orgs.remove_seats(purchase.enterprise, purchase.tier, quantity)
        return
    licence = Entitlement.objects.select_for_update().filter(pk=purchase.entitlement_id).first()
    if licence is None or not licence.is_active:
        return  # deleted with its account, or already withdrawn by staff: nothing to take
    # Asked after the lock: starting the survey locks the licence too.
    if Entitlement.objects.filter(pk=licence.pk, response__isnull=False).exists():
        raise Refused(STARTED)
    if purchase.kind == Purchase.Kind.UPGRADE:
        if licence.tier != purchase.tier:
            raise Refused(
                f"The licence is Tier {licence.tier} now, not the Tier {purchase.tier} this "
                "upgrade made it, so the upgrade cannot be undone here."
            )
        licences.change_tier(licence, purchase.from_tier)
        return
    paid_upgrades = licence.purchases.filter(
        kind=Purchase.Kind.UPGRADE,
        given_at__isnull=False,
        status__in=(Purchase.Status.PAID, Purchase.Status.PART_REFUNDED),
    )
    if paid_upgrades.exists():
        raise Refused(UPGRADE_ON_TOP)
    licences.revoke(licence)


def _record_refunded(purchase, amount, quantity):
    """Add a refund to the purchase's totals and set its status. The caller saves."""
    purchase.refunded_cents += amount
    purchase.refunded_quantity = min(purchase.quantity, purchase.refunded_quantity + quantity)
    purchase.status = (
        Purchase.Status.REFUNDED
        if purchase.refunded_cents >= purchase.amount_cents
        else Purchase.Status.PART_REFUNDED
    )
