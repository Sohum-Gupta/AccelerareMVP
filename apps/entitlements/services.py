"""
Every write to licences goes through here.

A bad tier or source raises django.core.exceptions.ValidationError, whose
message the admin can show. A licence is "unused" while it is active and no
response has consumed it. Access means an unused licence, or an open draft whose
licence has not been revoked. The queries reach responses through the reverse
names ("response"), so this module never imports the responses app.

Context. A licence is personal (it belongs to a person) or for one organization
(it belongs to a membership). The functions that ask "may this account take the
survey" take the context as `membership`: None for personal, or the account's
membership for that organization. The two never mix: a membership licence is
invisible to the personal context and the other way round. A deactivated
membership keeps its licences but cannot use them until it is reactivated.

The stock (Milestone 4). An organization buys licences per tier (its seat pools,
in the enterprises app) and its admins hand them out: assign_seat,
take_back_seat and change_seat_tier, at the bottom. Those three raise the
organization pages' own `Refused`, with a message the admin can be shown, or
`NotFound` when the member or licence is not that organization's. A licence
given this way has the source "seat" and is the only kind that counts against
the stock; one staff granted by hand is a gift on top and only staff change it.

Lock order, everywhere a licence is given, taken back or used: the
organization's row, then the membership, then the licences, then the response.
Starting the survey and erasing an account lock the membership before they touch
its licences or responses, so they take turns with the functions here.
"""

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.enterprises import services as orgs
from apps.enterprises.models import Membership
from apps.funnel import services as funnel

from .models import Entitlement

TIERS = (1, 2, 3)


def _check_tier(tier):
    # bool is an int in Python; True must not pass as tier 1.
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in TIERS:
        raise ValidationError("The tier must be 1, 2 or 3.")


DEACTIVATED_MEMBERSHIP = (
    "That membership is deactivated. Reactivate it before granting it a licence."
)


# What staff (and, later, a payment) may grant directly. A licence from an
# organization's stock is not granted this way: its admin gives it, within the
# stock, and that has its own rules.
GRANTABLE_SOURCES = (Entitlement.Source.PURCHASE, Entitlement.Source.MANUAL)


def _check_source(source):
    if source not in GRANTABLE_SOURCES:
        raise ValidationError("The source must be purchase or manual.")


def grant_individual(person, tier, source, granted_by=None):
    """Give a person one personal licence at the given tier."""
    _check_tier(tier)
    _check_source(source)
    entitlement = Entitlement.objects.create(
        person=person, tier=tier, source=source, granted_by=granted_by
    )
    funnel.record_event(funnel.Kind.LICENCE_GRANTED, tier=tier, source=source)
    return entitlement


def grant_for_membership(membership, tier, source, granted_by=None):
    """
    Give a membership one licence at the given tier: the member can then take the
    survey for that organization, and only for it. Refused for a deactivated
    membership, which could not use it.
    """
    _check_tier(tier)
    _check_source(source)
    if not membership.is_active:
        raise ValidationError(DEACTIVATED_MEMBERSHIP)
    entitlement = Entitlement.objects.create(
        membership=membership, tier=tier, source=source, granted_by=granted_by
    )
    funnel.record_event(funnel.Kind.LICENCE_GRANTED, tier=tier, source=source)
    return entitlement


def revoke(entitlement):
    """
    End a licence. The row stays; revoking twice keeps the first date. An
    unfinished attempt on it is deleted: it could never be continued, and while it
    existed the account could not start on any other licence of that context (one
    open draft per context). A submitted response is kept. Returns
    (entitlement, draft_deleted).
    """
    with transaction.atomic():
        # Held while responses.services.start_response is choosing a licence, so
        # a start and a revoke of the same licence take turns.
        locked = Entitlement.objects.select_for_update().get(pk=entitlement.pk)
        if locked.revoked_at is None:
            locked.revoked_at = timezone.now()
            locked.save(update_fields=["revoked_at"])
        entitlement.revoked_at = locked.revoked_at  # the caller's copy stays current
        draft = open_draft(locked)
        if draft is not None:
            draft.delete()
    return entitlement, draft is not None


def open_draft(entitlement):
    """The unfinished response on this licence, or None (through the reverse name)."""
    try:
        response = entitlement.response
    except ObjectDoesNotExist:
        return None
    return response if response.status == "draft" else None


def change_tier(entitlement, tier):
    """Upgrade (or correct) a licence in place; a revoked one is refused."""
    _check_tier(tier)
    if entitlement.revoked_at is not None:
        raise ValidationError("A revoked licence cannot be changed.")
    upgraded = tier > entitlement.tier
    entitlement.tier = tier
    entitlement.save(update_fields=["tier"])
    # Only a real step up is a funnel event: the admin calls this on every save,
    # and a correction downwards is not an upgrade.
    if upgraded:
        funnel.record_event(funnel.Kind.LICENCE_UPGRADED, tier=tier, source=entitlement.source)
    return entitlement


def _usable(account, membership):
    """
    The licences this account could use in this context, revoked or not: its
    person's for the personal context (membership None), the membership's for an
    organization. None of them if the membership is someone else's or is
    deactivated.
    """
    if membership is None:
        if account.person_id is None:
            return Entitlement.objects.none()
        return Entitlement.objects.filter(person_id=account.person_id)
    if membership.account_id != account.pk or not membership.is_active:
        return Entitlement.objects.none()
    return Entitlement.objects.filter(membership=membership)


def unused_licence(account, membership=None):
    """
    The oldest active licence in this context that no response has used, or None.
    The context is personal (membership None) or one organization.
    """
    return (
        _usable(account, membership)
        .filter(revoked_at__isnull=True, response__isnull=True)
        .order_by("granted_at", "id")
        .first()
    )


def has_survey_access(account, membership=None):
    """True if the account may take (or carry on with) the survey in this context."""
    open_draft = (
        _usable(account, membership)
        .filter(response__account=account, response__status="draft", revoked_at__isnull=True)
        .exists()
    )
    return open_draft or unused_licence(account, membership) is not None


# --- licences from an organization's stock -----------------------------------------

# The plain-words refusal the organization pages already catch and show.
Refused = orgs.Refused


class NotFound(Refused):
    """The member or the licence is not this organization's. A page answers "not found"."""


MEMBER_NOT_FOUND = "That member was not found."
LICENCE_NOT_FOUND = "That licence was not found."
ALREADY_HAS_ONE = "They already have a licence they have not used."
STILL_TAKING = "They have not finished the survey on the licence they already have."
NOT_FROM_STOCK = (
    "This licence was granted by Accelerare, not given from your organization's stock, "
    "so it cannot be changed here."
)
ALREADY_TAKEN_BACK = "That licence has already been taken back."
SUBMITTED_SO_KEPT = "The survey on this licence has been submitted, so it cannot be taken back."


def assign_seat(admin_membership, member_membership, tier):
    """
    An organization's admin gives one of its members a licence of this tier out
    of the organization's stock, and the new licence is returned. An admin is a
    member too and can give one to themselves.

    Refused when the stock of that tier has none left, when the member is
    deactivated, and when the member already holds a licence for the
    organization that they have not used or have not finished using (whoever it
    came from): after they submit they can be given another.
    """
    _check_seat_tier(tier)
    with transaction.atomic():
        enterprise, admin = orgs.lock_for_admin(admin_membership)
        member = (
            Membership.objects.select_for_update()
            .filter(pk=member_membership.pk, enterprise_id=enterprise.pk)
            .first()
        )
        if member is None:
            raise NotFound(MEMBER_NOT_FOUND)
        if not member.is_active:
            raise Refused(
                "This member has been deactivated. Reactivate them before giving them a licence."
            )
        # Lock the member's active licences on their own (no join), then ask the
        # questions in fresh statements, which see what was committed meanwhile.
        held = Entitlement.objects.filter(membership=member, revoked_at__isnull=True)
        list(held.select_for_update())
        if held.filter(response__isnull=True).exists():
            raise Refused(ALREADY_HAS_ONE)
        if held.filter(response__status="draft").exists():
            raise Refused(STILL_TAKING)
        _check_one_left(enterprise, tier)
        entitlement = Entitlement.objects.create(
            membership=member,
            tier=tier,
            source=Entitlement.Source.SEAT,
            granted_by=admin.account,
        )
        funnel.record_event(funnel.Kind.LICENCE_GRANTED, tier=tier, source=Entitlement.Source.SEAT)
        return entitlement


def take_back_seat(admin_membership, entitlement):
    """
    An organization's admin takes back a licence given from its stock, which
    puts it back in the stock. Allowed until the survey on it is submitted: an
    unfinished attempt is deleted (the page warns first), and a deactivated
    member's licence can be taken back too. Once submitted, the licence is
    spent. The licence is revoked, never deleted, so there is a record.
    Returns (entitlement, draft_deleted), like revoke.
    """
    with transaction.atomic():
        enterprise, _ = orgs.lock_for_admin(admin_membership)
        licence = _locked_seat(enterprise, entitlement)
        response = _locked_response(licence)
        if response is not None and response.status != "draft":
            raise Refused(SUBMITTED_SO_KEPT)
        return revoke(licence)


def change_seat_tier(admin_membership, entitlement, tier):
    """
    An organization's admin moves a licence from its stock to another tier: up
    or down until the survey on it is submitted, only up afterwards. The new
    tier must have one left; the old tier gets one back, because a licence
    counts against the tier it has now. Returns the licence.
    """
    _check_seat_tier(tier)
    with transaction.atomic():
        enterprise, _ = orgs.lock_for_admin(admin_membership)
        licence = _locked_seat(enterprise, entitlement)
        if tier == licence.tier:
            return licence
        response = _locked_response(licence)
        if response is not None and response.status != "draft" and tier < licence.tier:
            raise Refused(
                "The survey on this licence has been submitted, so its tier can only go up."
            )
        _check_one_left(enterprise, tier)
        return change_tier(licence, tier)


def _check_seat_tier(tier):
    # bool is an int in Python, and 2.0 == 2: neither may pass as a tier.
    if isinstance(tier, bool) or not isinstance(tier, int) or tier not in TIERS:
        raise Refused("The tier must be 1, 2 or 3.")


def _check_one_left(enterprise, tier):
    """Refuse unless the stock of this tier has a licence left. The caller holds the lock."""
    left = next(row["left"] for row in orgs.seat_summary(enterprise) if row["tier"] == tier)
    if left < 1:
        raise Refused(f"There are no Tier {tier} licences left to give.")


def _locked_seat(enterprise, entitlement):
    """
    This organization's licence as it is now, with its membership and then
    itself locked; the caller holds the organization's lock. NotFound for a
    personal licence or another organization's, Refused for one that did not
    come from the stock or has already been taken back.
    """
    membership_id = (
        Entitlement.objects.filter(pk=entitlement.pk, membership__enterprise_id=enterprise.pk)
        .values_list("membership_id", flat=True)
        .first()
    )
    if membership_id is None:
        raise NotFound(LICENCE_NOT_FOUND)
    # The membership first: starting the survey and erasing the account hold it
    # while they work on its licences and responses. Both rows can have gone by
    # the time the lock is ours (the account was erased), hence "not found".
    if not list(Membership.objects.select_for_update().filter(pk=membership_id)):
        raise NotFound(LICENCE_NOT_FOUND)
    licence = (
        Entitlement.objects.select_for_update()
        .filter(pk=entitlement.pk, membership_id=membership_id)
        .first()
    )
    if licence is None:
        raise NotFound(LICENCE_NOT_FOUND)
    if licence.source != Entitlement.Source.SEAT:
        raise Refused(NOT_FROM_STOCK)
    if licence.revoked_at is not None:
        raise Refused(ALREADY_TAKEN_BACK)
    return licence


def _locked_response(entitlement):
    """
    The response on this licence, locked, or None. Submitting locks the same
    row, so "has it been submitted" is asked on settled data: a member pressing
    Submit and an admin taking the licence back take turns. Reached through the
    reverse name, so this module still never imports the responses app.
    """
    responses = Entitlement._meta.get_field("response").related_model
    return responses.objects.select_for_update().filter(entitlement_id=entitlement.pk).first()
