"""
Organizations: who belongs to which, and how they got in.

The site says "organization"; the code, the tables and the docs say "enterprise"
for the same thing. An Enterprise is the organization. A Membership links one
account to one enterprise, as a member or an admin, and is never deleted when
someone leaves: it is deactivated, so the organization keeps its history. The
only two ways in are an Invite (one email address, one use) and a JoinCode (a
shared code with a cap on its uses).

Nothing here knows about licences or surveys. Those apps point at a membership
(`membership.entitlements`, `membership.responses`), never the other way round:
the dependencies run accounts <- enterprises <- entitlements <- responses.

No `__str__` below contains an email or a person's name. Django's admin history
stores an object's `str()` as its label, and a label must not keep someone's
identity after they have been erased.

All writes go through services.py; the models only describe the shape and the
database rules.
"""

from django.conf import settings
from django.db import models

TIER_1_TO_3_OR_NONE = models.Q(tier__isnull=True) | models.Q(tier__gte=1, tier__lte=3)


class Enterprise(models.Model):
    """One organization. Anyone with a verified email can create one."""

    # Two organizations may share a name; the slug is what tells them apart.
    name = models.CharField(max_length=120)
    # The part of the address after /organizations/. Unique, made from the name.
    slug = models.SlugField(max_length=80, unique=True)
    # Kept for the record; emptied if that account is ever deleted.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # How many people the organization may bring in before it has bought
    # licences: every invite ever sent plus every join by code. The creator does
    # not count. Staff raise it by hand in the admin (backlog D-16).
    people_limit = models.PositiveIntegerField(default=25)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "organization"

    def __str__(self):
        return self.name


class Membership(models.Model):
    """
    One account in one organization. An admin is also a member. A membership is
    deactivated when the person leaves and reactivated if they come back; the
    row itself stays, so there is at most one per account and organization.
    """

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        ADMIN = "admin", "Admin"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"

    # PROTECT on both: a membership never disappears as a side effect. Erasing
    # an account (accounts/erasure.py) decides what happens to its memberships.
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    enterprise = models.ForeignKey(
        Enterprise,
        on_delete=models.PROTECT,
        related_name="memberships",
        verbose_name="organization",  # the word staff see in the admin
    )
    role = models.CharField(max_length=10, choices=Role, default=Role.MEMBER)
    status = models.CharField(max_length=15, choices=Status, default=Status.ACTIVE)
    joined_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    # How this person most recently got in. Both empty for the creator and for
    # an admin that staff appointed.
    joined_via_invite = models.ForeignKey(
        "Invite", null=True, blank=True, on_delete=models.SET_NULL, related_name="memberships"
    )
    joined_via_code = models.ForeignKey(
        "JoinCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="memberships"
    )

    class Meta:
        ordering = ["joined_at", "id"]
        # What Support staff are given in the staff admin: they may deactivate a
        # membership, and change nothing else about one (apps/responses/signals.py).
        permissions = [("deactivate_membership", "Can deactivate a membership")]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "enterprise"], name="membership_one_per_account_and_enterprise"
            ),
            # A deactivated membership says when; an active one has no such date.
            models.CheckConstraint(
                condition=(
                    models.Q(status="active", deactivated_at__isnull=True)
                    | models.Q(status="deactivated", deactivated_at__isnull=False)
                ),
                name="membership_deactivated_at_iff_deactivated",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["member", "admin"]),
                name="membership_role_is_member_or_admin",
            ),
            # Leaving also ends being an admin: someone who comes back is an
            # ordinary member until an admin promotes them again.
            models.CheckConstraint(
                condition=models.Q(status="active") | models.Q(role="member"),
                name="membership_deactivated_is_a_member",
            ),
            # Someone joins one way, not two.
            models.CheckConstraint(
                condition=(
                    models.Q(joined_via_invite__isnull=True)
                    | models.Q(joined_via_code__isnull=True)
                ),
                name="membership_joined_one_way",
            ),
        ]

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    def __str__(self):
        # The organization's name is not personal; the person is left out on purpose.
        return f"Membership {self.pk} in {self.enterprise.name}"


class Invite(models.Model):
    """
    An invitation sent to one email address. Single use, and it expires. It can
    be accepted only by an account that has verified that address; the link
    proves nothing by itself.
    """

    enterprise = models.ForeignKey(
        Enterprise,
        on_delete=models.PROTECT,
        related_name="invites",
        verbose_name="organization",  # the word staff see in the admin
    )
    # Lowercased, like ContactPoint.value_normalised. Emptied when the person
    # it was sent to is erased; the row stays because it still counts towards
    # the organization's people limit.
    email = models.EmailField(blank=True)
    # The secret in the link. Long and random; never shown in a list.
    token = models.CharField(max_length=64, unique=True)
    # Stored but unused until Milestone 4 gives it a meaning (a seat at that tier).
    tier = models.PositiveSmallIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=TIER_1_TO_3_OR_NONE, name="invite_tier_1_to_3_or_none"
            ),
            # Used or withdrawn, never both.
            models.CheckConstraint(
                condition=models.Q(accepted_at__isnull=True) | models.Q(revoked_at__isnull=True),
                name="invite_not_both_accepted_and_revoked",
            ),
        ]

    def __str__(self):
        return f"Invite {self.pk}"


class JoinCode(models.Model):
    """
    A code an admin hands out (on a slide, in a chat). Anyone who has it can join
    until it runs out of uses, expires or is revoked.
    """

    enterprise = models.ForeignKey(
        Enterprise,
        on_delete=models.PROTECT,
        related_name="join_codes",
        verbose_name="organization",  # the word staff see in the admin
    )
    # Ten characters, uppercase, no hyphen; shown as XXXXX-XXXXX.
    code = models.CharField(max_length=10, unique=True)
    tier = models.PositiveSmallIntegerField(null=True, blank=True)
    max_uses = models.PositiveIntegerField()
    uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=TIER_1_TO_3_OR_NONE, name="joincode_tier_1_to_3_or_none"
            ),
            models.CheckConstraint(
                condition=models.Q(max_uses__gte=1), name="joincode_at_least_one_use"
            ),
            # The backstop behind the row lock in services.redeem_code.
            models.CheckConstraint(
                condition=models.Q(uses__lte=models.F("max_uses")),
                name="joincode_uses_never_exceed_max_uses",
            ),
        ]

    def __str__(self):
        # Not the code itself: a history label is no place for a working code.
        return f"Join code {self.pk}"
