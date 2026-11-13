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
"""

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone

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
