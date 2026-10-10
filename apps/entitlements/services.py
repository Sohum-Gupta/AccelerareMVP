"""
Every write to licences goes through here.

A bad tier or source raises django.core.exceptions.ValidationError, whose
message the admin can show. A licence is "unused" while it is active and no
response has consumed it. Access means an unused licence, or an open draft whose
licence has not been revoked. The queries reach responses through the reverse
names ("response"), so this module never imports the responses app.
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


def grant_individual(person, tier, source, granted_by=None):
    """Give a person one licence at the given tier."""
    _check_tier(tier)
    if source not in Entitlement.Source.values:
        raise ValidationError("The source must be purchase or manual.")
    entitlement = Entitlement.objects.create(
        person=person, tier=tier, source=source, granted_by=granted_by
    )
    funnel.record_event(funnel.Kind.LICENCE_GRANTED, tier=tier, source=source)
    return entitlement


def revoke(entitlement):
    """
    End a licence. The row stays; revoking twice keeps the first date. An
    unfinished attempt on it is deleted: it could never be continued, and while it
    existed the account could not start on any other licence (one open draft per
    account). A submitted response is kept. Returns (entitlement, draft_deleted).
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


def unused_licence(account):
    """The account person's oldest active licence that no response has used, or None."""
    return (
        Entitlement.objects.filter(
            person=account.person, revoked_at__isnull=True, response__isnull=True
        )
        .order_by("granted_at", "id")
        .first()
    )


def has_survey_access(account):
    open_draft = Entitlement.objects.filter(
        response__account=account, response__status="draft", revoked_at__isnull=True
    ).exists()
    return open_draft or unused_licence(account) is not None
