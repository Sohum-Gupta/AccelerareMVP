"""
Licences: who may take the survey, and which results they may see.

An Entitlement is one licence. It buys one survey attempt plus the results at its
tier (1 to 3), and can be upgraded in place.

A licence belongs either to a Person (a personal licence) or to a Membership (a
licence for one organization), never both and never neither. That choice is the
context of the attempt it buys: a membership licence can only be used for that
organization, and the organization's admins can then see that the survey was
taken (never the answers); a personal licence can only be used personally, and
no organization sees anything. Because the response points at exactly one
licence, the two can never disagree. Until Milestone 4 adds seats, staff grant
both kinds by hand in the admin.

It is revoked, never deleted, so there is a record of what was granted and a
response linked to it keeps something to point at.

All writes go through services.py; the models only describe the shape and the
database rules.
"""

from django.db import models


class Entitlement(models.Model):
    class Source(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        MANUAL = "manual", "Granted by hand"
        # Given to a member by their organization's admin, out of the licences
        # the organization bought (enterprises.SeatPool). Only these count
        # against that stock.
        SEAT = "seat", "From the organization's stock"

    # Exactly one of these two is set (a database rule, below).
    # PROTECT: a person or a membership cannot be deleted while a licence points at it.
    person = models.ForeignKey(
        "accounts.Person",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="entitlements",
    )
    membership = models.ForeignKey(
        "enterprises.Membership",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="entitlements",
    )
    tier = models.PositiveSmallIntegerField()
    source = models.CharField(max_length=20, choices=Source)
    # Who granted it by hand; empty for a purchase, and kept if that account goes.
    granted_by = models.ForeignKey(
        "accounts.Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["granted_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tier__gte=1, tier__lte=3),
                name="entitlement_tier_1_to_3",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(person__isnull=False, membership__isnull=True)
                    | models.Q(person__isnull=True, membership__isnull=False)
                ),
                name="entitlement_person_or_membership_not_both",
            ),
        ]

    @property
    def is_active(self):
        return self.revoked_at is None

    @property
    def is_personal(self):
        return self.membership_id is None

    def __str__(self):
        if self.membership_id is not None:
            return f"Tier {self.tier} licence for membership {self.membership_id}"
        return f"Tier {self.tier} licence for person {self.person_id}"
