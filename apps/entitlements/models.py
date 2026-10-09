"""
Licences: who may take the survey, and which results they may see.

An Entitlement is one licence. It buys one survey attempt plus the results at its
tier (1 to 3), and can be upgraded in place. This is the individual half: it
belongs to a Person. Milestone 4 adds the enterprise half (a nullable membership
and the "seat" source) to this same table.

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

    # PROTECT: a person cannot be deleted while a licence points at them.
    person = models.ForeignKey(
        "accounts.Person", on_delete=models.PROTECT, related_name="entitlements"
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
        ]

    @property
    def is_active(self):
        return self.revoked_at is None

    def __str__(self):
        return f"Tier {self.tier} licence for person {self.person_id}"
