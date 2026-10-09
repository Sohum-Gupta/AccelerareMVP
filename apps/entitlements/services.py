"""
Every write to licences goes through here.

A bad tier or source raises django.core.exceptions.ValidationError, whose
message the admin can show. Until the Response model exists (next PRs), "unused"
means "active": once responses link to licences, unused_licence also skips a
licence a response already consumed, and has_survey_access also counts an open
draft.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone

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
    return Entitlement.objects.create(
        person=person, tier=tier, source=source, granted_by=granted_by
    )


def revoke(entitlement):
    """End a licence. The row stays; revoking twice keeps the first date."""
    if entitlement.revoked_at is None:
        entitlement.revoked_at = timezone.now()
        entitlement.save(update_fields=["revoked_at"])
    return entitlement


def change_tier(entitlement, tier):
    """Upgrade (or correct) a licence in place; a revoked one is refused."""
    _check_tier(tier)
    if entitlement.revoked_at is not None:
        raise ValidationError("A revoked licence cannot be changed.")
    entitlement.tier = tier
    entitlement.save(update_fields=["tier"])
    return entitlement


def unused_licence(account):
    """The account person's oldest active licence, or None."""
    return (
        Entitlement.objects.filter(person=account.person, revoked_at__isnull=True)
        .order_by("granted_at", "id")
        .first()
    )


def has_survey_access(account):
    return unused_licence(account) is not None
