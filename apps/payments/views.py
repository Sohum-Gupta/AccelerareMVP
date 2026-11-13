"""
The buy pages, where Stripe sends a person back to, and where Stripe sends its
own messages.

`buy` is a person's own page: the three tiers with their prices, and the
licences they hold that can be moved up a tier. Its buttons post only a tier;
the price is read on the server. `buy_stock` is the same for an organization's
admin, in buy_stock.py's place in config/urls.py beside the Licences page: it
starts with scoping.for_admin, like every page about one organization, so
another organization's address is "not found". Each button ends by sending the
person to Stripe's payment page. The templates get plain values, never a
database object.

`done` and `cancelled` are the two ways back from Stripe's payment page
(`cancelled` returns to the buy page the person left). `done`
carries Stripe's id for the page in its address. That id is looked up among
this person's own purchases (anyone else's is "not found") and then Stripe is
asked whether it was paid: nothing in the address is believed by itself.

`stripe_webhook` is not for people. Stripe calls it to say a payment went
through or was refunded. It cannot carry our login or our form token, so the
only proof of who is calling is Stripe's signature on the body, which is
checked before anything is read. A failure while handling a message is not
caught: Stripe then sends it again later, and the handlers are safe to run twice.
"""

from django.contrib import messages
from django.db.models import F
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import verified_email_required
from apps.enterprises import scoping
from apps.enterprises.shown import organization
from apps.entitlements.models import Entitlement

from . import services, stripe_api
from .forms import BuyStockForm, TierForm
from .models import Purchase

# --- a person buys for themselves ---------------------------------------------------------


def _shown_prices():
    """{tier: "$2.00"} for the tiers that have a price."""
    return {tier: services.dollars(cents) for tier, cents in sorted(services.prices().items())}


def _own_licences(account):
    """
    The person's own licences that are not withdrawn, oldest first, each with
    the status of the survey taken on it (`survey`: empty if none was started).
    Read as one column through the reverse name: the answers are never loaded.
    """
    if account.person_id is None:
        return Entitlement.objects.none()
    return (
        Entitlement.objects.filter(person_id=account.person_id, revoked_at__isnull=True)
        .annotate(survey=F("response__status"))
        .order_by("granted_at", "id")
    )


def _licence_row(licence):
    """What the page says about one of the person's licences, and the upgrades on offer."""
    if licence.survey is None:
        state = "unused"
    else:
        state = "in_progress" if licence.survey == "draft" else "submitted"
    return {
        "id": licence.pk,
        "tier": licence.tier,
        "state": state,
        "upgrades": [
            {"tier": tier, "cost": services.dollars(cents)}
            for tier, cents in services.upgrades_for(licence).items()
        ],
    }


@never_cache
@require_GET
@verified_email_required
def buy(request):
    """Buy a personal licence, or move one you hold up a tier."""
    context = {
        "open": services.is_open(),
        "closed": services.NOT_OPEN,
        "tiers": [{"tier": tier, "price": price} for tier, price in _shown_prices().items()],
        "licences": [_licence_row(licence) for licence in _own_licences(request.user)],
    }
    return render(request, "payments/buy.html", context)


def _tier(request):
    """The tier a Buy or Upgrade button sent, as a number, or None if it is not one."""
    form = TierForm(request.POST)
    return form.cleaned_data["tier"] if form.is_valid() else None


@require_POST
@verified_email_required
def buy_personal(request):
    """The Buy button: start a purchase and send the person to Stripe's payment page."""
    try:
        return redirect(services.start_personal(request.user, _tier(request), request=request))
    except services.Refused as error:
        messages.error(request, str(error))
        return redirect("payments:buy")


@require_POST
@verified_email_required
def buy_upgrade(request, pk):
    """The Upgrade button on one of the person's own licences."""
    licence = get_object_or_404(_own_licences(request.user), pk=pk)
    try:
        return redirect(
            services.start_upgrade(request.user, licence, _tier(request), request=request)
        )
    except services.NotFound:
        raise Http404 from None
    except services.Refused as error:
        messages.error(request, str(error))
        return redirect("payments:buy")


# --- an organization's admin buys for its stock -------------------------------------------


@never_cache
@require_http_methods(["GET", "POST"])
@verified_email_required
def buy_stock(request, slug):
    """An organization's admin buys licences of one tier into its stock."""
    membership = scoping.for_admin(request, slug)
    prices = _shown_prices()
    form = BuyStockForm(request.POST or None, prices=prices)
    if request.method == "POST" and form.is_valid():
        try:
            return redirect(
                services.start_stock(
                    membership,
                    form.cleaned_data["tier"],
                    form.cleaned_data["quantity"],
                    request=request,
                )
            )
        except services.Refused as error:
            form.add_error(None, str(error))
    context = {
        "organization": organization(membership),
        "open": services.is_open(),
        "closed": services.NOT_OPEN,
        "form": form,
        "most": services.MAX_STOCK_PER_PURCHASE,
    }
    return render(request, "payments/buy_stock.html", context)


# --- back from Stripe ---------------------------------------------------------------------


def _back_to(purchase):
    """Where someone lands after paying, or not paying, for this purchase."""
    if purchase is not None and purchase.kind == Purchase.Kind.STOCK:
        return redirect("organization_licences", purchase.enterprise.slug)
    return redirect("responses:history")


def _thanks(purchase):
    if purchase.kind == Purchase.Kind.STOCK:
        number = purchase.quantity
        noun = "licence has" if number == 1 else "licences have"
        return (
            f"Thank you. {number:,} Tier {purchase.tier} {noun} been added to "
            f"{purchase.enterprise.name}'s stock."
        )
    if purchase.kind == Purchase.Kind.UPGRADE:
        return f"Thank you. Your licence is now Tier {purchase.tier}."
    return f"Thank you. Your Tier {purchase.tier} licence is ready."


@never_cache
@require_GET
@verified_email_required
def done(request):
    """Back from Stripe after paying: give what was paid for if Stripe confirms it, and say so."""
    session_id = request.GET.get("session_id", "")
    purchase = (
        Purchase.objects.select_related("enterprise")
        .filter(stripe_session_id=session_id, buyer=request.user)
        .first()
        if session_id
        else None
    )
    if purchase is None:
        raise Http404
    if purchase.status == Purchase.Status.PENDING:
        try:
            purchase = services.fulfil(stripe_api.get_checkout(session_id)) or purchase
        except (stripe_api.StripeFailed, stripe_api.NotConfigured):
            pass  # Stripe's own message will do it; say it is being confirmed
    if purchase.status == Purchase.Status.PENDING:
        messages.info(
            request,
            "Your payment is being confirmed. What you bought will appear here within "
            "a minute or two: reload this page.",
        )
    elif purchase.needs_attention:
        messages.warning(
            request,
            "Your payment went through, but we could not finish our side of it. "
            "We have been told, and will put it right or refund you.",
        )
    elif purchase.status == Purchase.Status.PAID:
        messages.success(request, _thanks(purchase))
    return _back_to(purchase)


@never_cache
@require_GET
@verified_email_required
def cancelled(request):
    """Back from Stripe without paying."""
    purchase = None
    if request.GET.get("purchase", "").isdigit():
        purchase = (
            Purchase.objects.select_related("enterprise")
            .filter(pk=request.GET["purchase"], buyer=request.user)
            .first()
        )
    messages.info(request, "Nothing was charged. You can buy whenever you like.")
    if purchase is not None and purchase.kind == Purchase.Kind.STOCK:
        return redirect("organization_licences_buy", purchase.enterprise.slug)
    return redirect("payments:buy")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Stripe telling the site that a payment went through, or that money went back."""
    try:
        event = stripe_api.read_event(request.body, request.headers.get("Stripe-Signature"))
    except stripe_api.NotConfigured:
        # No secret to check with yet. Stripe keeps trying for days.
        return HttpResponse("Not set up.", status=503, content_type="text/plain")
    except stripe_api.BadSignature:
        return HttpResponse("Bad signature.", status=400, content_type="text/plain")
    if event["type"] == "checkout.session.completed":
        services.fulfil(stripe_api.checkout_in(event))
    elif event["type"] == "charge.refunded":
        services.record_outside_refund(stripe_api.charge_in(event))
    # Any other kind of message is one the site does not use: say "fine".
    return HttpResponse("ok", content_type="text/plain")
