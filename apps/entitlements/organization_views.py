"""
An organization admin's Licences page, /organizations/<slug>/licences/, and its
three buttons: give a member a licence out of the organization's stock, change
a licence's tier, and take one back (which asks first).

The pages live here, not with the other organization pages, for the same reason
the responses pages live in the responses app: the apps depend on each other
one way (accounts <- enterprises <- entitlements <- responses), so the
enterprises app may not import a licence. They are listed in config/urls.py.

Thin views: find the organization, call a service, show what it said. Every
rule (is one left, was it submitted, did it come from the stock) is in
services.py and is checked there again under lock, whatever the page offered.

How one organization is kept apart from another:

* Every view starts with scoping.for_admin: the slug only says which
  organization is meant, and what comes back is this account's own active
  admin membership, or "not found".
* A member id or a licence id in an address is looked up inside that
  organization (_their_member, _their_licence), so another organization's id
  is "not found", the same answer as an id that does not exist. A personal
  licence belongs to no membership, so it can never match.
* The templates get plain values, never a database object.

What an admin is told about the survey on a licence is only whether it has not
been started, is in progress or is submitted, which the responses pages tell
them already. It is read as one column (the response's status, through the
reverse name), so the answers are not read from the database at all, and this
app still never imports the responses app.

tests/test_tenant_isolation.py holds all of this to account.
"""

from django.contrib import messages
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import verified_email_required
from apps.enterprises import scoping
from apps.enterprises import services as orgs
from apps.enterprises.models import Membership
from apps.enterprises.shown import member_email, member_name, organization

from . import services
from .forms import TierForm
from .models import Entitlement

UNUSED, IN_PROGRESS, SUBMITTED = "unused", "in_progress", "submitted"
CHOOSE_A_TIER = "Choose a tier from the list."


def _licences(enterprise):
    """
    Every licence that belongs to a membership of this organization, each with
    the status of the survey taken on it (`survey`: empty if none was started).
    """
    return Entitlement.objects.filter(membership__enterprise=enterprise).annotate(
        survey=F("response__status")
    )


def _state(licence):
    if licence.survey is None:
        return UNUSED
    return IN_PROGRESS if licence.survey == "draft" else SUBMITTED


def _stock(enterprise):
    """The stock lines a page shows: the tiers the organization has bought or holds."""
    return [line for line in orgs.seat_summary(enterprise) if line["bought"] or line["given"]]


def _licence_facts(licence, tiers_left):
    """What an admin sees of one licence, and what the page offers to do with it."""
    state = _state(licence)
    from_stock = licence.source == Entitlement.Source.SEAT
    # Up or down until the survey is submitted, only up afterwards; and only to
    # a tier that has one left. One that staff granted is not the admin's to change.
    move_to = [
        tier
        for tier in tiers_left
        if from_stock and tier != licence.tier and (state != SUBMITTED or tier > licence.tier)
    ]
    return {
        "id": licence.pk,
        "tier": licence.tier,
        "state": state,
        "from_stock": from_stock,
        "can_take_back": from_stock and state != SUBMITTED,
        "move_to": move_to,
    }


def _member_facts(person, held, viewer, tiers_left):
    """What the page shows for one member. Plain values only."""
    shown = [_licence_facts(licence, tiers_left) for licence in held]
    return {
        "id": person.pk,
        "name": member_name(person.account),
        "email": member_email(person),
        "erased": person.account.anonymised_at is not None,
        "active": person.is_active,
        "is_you": person.pk == viewer.pk,
        "licences": shown,
        # One licence at a time: another can be given once the last is submitted.
        "can_give": person.is_active and all(one["state"] == SUBMITTED for one in shown),
    }


@never_cache
@require_GET
@verified_email_required
def licences(request, slug):
    """
    The organization's stock, tier by tier, and its members with the licences
    they hold. Members who have left are listed only while they still hold one.
    A licence that has been taken back is not shown.
    """
    membership = scoping.for_admin(request, slug)
    enterprise = membership.enterprise
    stock = _stock(enterprise)
    tiers_left = [line["tier"] for line in stock if line["left"]]

    held = {}
    for licence in _licences(enterprise).filter(revoked_at__isnull=True):
        held.setdefault(licence.membership_id, []).append(licence)
    people = [
        person
        for person in enterprise.memberships.select_related("account", "joined_via_invite")
        if person.is_active or person.pk in held
    ]
    people.sort(key=lambda person: (not person.is_active, person.joined_at, person.pk))

    context = {
        "organization": organization(membership),
        "stock": stock,
        "give_tiers": tiers_left,
        "rows": [
            _member_facts(person, held.get(person.pk, []), membership, tiers_left)
            for person in people
        ],
    }
    return render(request, "entitlements/licences.html", context)


# --- the buttons -------------------------------------------------------------------


def _their_member(membership, pk):
    """A member of the admin's own organization. Any other id is "not found"."""
    return get_object_or_404(
        Membership.objects.select_related("account"),
        pk=pk,
        enterprise_id=membership.enterprise_id,
    )


def _their_licence(membership, pk):
    """A licence of the admin's own organization. Any other id is "not found"."""
    return get_object_or_404(
        _licences(membership.enterprise).select_related("membership__account"), pk=pk
    )


def _tier(request):
    """The tier chosen in the drop-down, as a number, or None if it is not one."""
    form = TierForm(request.POST)
    return form.cleaned_data["tier"] if form.is_valid() else None


def _back(membership):
    return redirect("organization_licences", membership.enterprise.slug)


@verified_email_required
@require_POST
def give(request, slug, pk):
    """Give one member a licence of the chosen tier, out of the stock."""
    membership = scoping.for_admin(request, slug)
    member = _their_member(membership, pk)
    tier = _tier(request)
    if tier is None:
        messages.error(request, CHOOSE_A_TIER)
        return _back(membership)
    try:
        services.assign_seat(membership, member, tier)
    except services.NotFound:
        raise Http404 from None
    except services.Refused as error:
        messages.error(request, str(error))
    else:
        who = "You now have" if member.pk == membership.pk else _who(member.account) + " now has"
        messages.success(request, f"{who} a Tier {tier} licence.")
    return _back(membership)


@verified_email_required
@require_POST
def change_tier(request, slug, pk):
    """Move a licence from the stock to another tier."""
    membership = scoping.for_admin(request, slug)
    licence = _their_licence(membership, pk)
    tier = _tier(request)
    if tier is None:
        messages.error(request, CHOOSE_A_TIER)
        return _back(membership)
    try:
        services.change_seat_tier(membership, licence, tier)
    except services.NotFound:
        raise Http404 from None
    except services.Refused as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"The licence is now Tier {tier}.")
    return _back(membership)


@never_cache
@verified_email_required
def take_back(request, slug, pk):
    """
    Take a licence back into the stock: first a page that says what will
    happen, then the POST that does it. It asks first because taking back a
    licence whose survey has been started deletes that unfinished survey.
    """
    membership = scoping.for_admin(request, slug)
    licence = _their_licence(membership, pk)
    if request.method == "POST":
        try:
            _, draft_deleted = services.take_back_seat(membership, licence)
        except services.NotFound:
            raise Http404 from None
        except services.Refused as error:
            messages.error(request, str(error))
        else:
            said = f"The Tier {licence.tier} licence is back in your stock."
            if draft_deleted:
                said += " The unfinished survey on it was deleted."
            messages.success(request, said)
        return _back(membership)

    # Nothing to confirm if it cannot be taken back: say why instead. The
    # service decides again, under lock, when the button is pressed.
    state = _state(licence)
    reason = ""
    if licence.source != Entitlement.Source.SEAT:
        reason = services.NOT_FROM_STOCK
    elif licence.revoked_at is not None:
        reason = services.ALREADY_TAKEN_BACK
    elif state == SUBMITTED:
        reason = services.SUBMITTED_SO_KEPT
    if reason:
        messages.error(request, reason)
        return _back(membership)
    context = {
        "organization": organization(membership),
        "licence": {
            "id": licence.pk,
            "tier": licence.tier,
            "in_progress": state == IN_PROGRESS,
            "name": member_name(licence.membership.account),
        },
    }
    return render(request, "entitlements/take_back.html", context)


def _who(account):
    """How a message names the member: by name if there is one."""
    return member_name(account) or "The member"
