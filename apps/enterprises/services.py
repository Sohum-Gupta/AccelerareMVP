"""
Every write to an organization goes through here: creating one, join codes,
roles, deactivating and reactivating. Views and the staff admin stay thin: they
call one of these functions and show the result, so a web page, an admin action
and a test all enforce the same rules.

The rules (decided by the founder on 2026-11-12):

* Anyone with a verified email can create an organization and becomes its first
  admin. An account can create three itself; staff can create more for it.
* An admin is also a member. An organization always has at least one active
  admin: the last one can be neither demoted nor deactivated.
* Deactivating someone also makes them an ordinary member, so a returning admin
  has to be promoted again on purpose.
* The people limit: until an organization has bought licences it can bring in
  `people_limit` people in total (25 by default). Every invite ever sent counts,
  whatever became of it, and so does every join by code, so revoking and
  resending does not get round it. The creator does not count.
* A join code works until it is revoked, expires or runs out of uses. A
  deactivated member cannot come back with a code; an admin reactivates them.

Who is acting: a function that an organization's admin can call takes `by`, the
acting admin's own Membership, and checks again that it is an active admin of
the same organization. Staff working in the Django admin pass nothing (`by=None`);
the admin site has already checked their permissions.

Concurrency: anything that counts (places left, uses of a code, how many admins
remain) first locks the organization's row, so two requests for the same
organization take turns, and then the row it changes. The locks are plain
single-table reads; a lock on a join is unreliable (see NOTES.md).

A refused action raises Refused, whose message is plain words for the page.
"""

import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts import services as accounts
from apps.accounts.models import Account

from .models import Enterprise, JoinCode, Membership

# How many organizations one account may create by itself. Each one can send
# its own invites, so this is what keeps the people limit meaningful.
MAX_CREATED_PER_ACCOUNT = 3
NAME_MAX_LENGTH = 120  # the same number as Enterprise.name
# Addresses under /organizations/ that are pages, not organizations.
RESERVED_SLUGS = {"new"}

# Ten characters from 31: letters and digits that cannot be misread for one
# another (no 0 or O, no 1, I or L). About 8 x 10^14 possible codes.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10
DEFAULT_CODE_DAYS = 30
MAX_CODE_USES = 10_000
TIERS = (1, 2, 3)


class Refused(Exception):
    """An action the rules do not allow. str(error) is plain words for the person."""


class AlreadyMember(Refused):
    """The account already belongs to the organization (the page can simply take them there)."""


# --- reads ---------------------------------------------------------------------


def places_left(enterprise):
    """
    How many more people the organization may bring in: its limit, less every
    invite ever sent (accepted, pending, revoked or expired) and every join by
    code. Never below zero, even after staff lower the limit.
    """
    invites = enterprise.invites.count()
    code_joins = enterprise.join_codes.aggregate(total=Sum("uses"))["total"] or 0
    return max(0, enterprise.people_limit - invites - code_joins)


def normalise_code(typed):
    """A join code as stored: uppercase, with the hyphen and any spaces dropped."""
    return "".join(str(typed or "").split()).replace("-", "").upper()


def display_code(code):
    """A join code as shown: XXXXX-XXXXX."""
    return f"{code[:5]}-{code[5:]}"


# --- creating an organization --------------------------------------------------


def create_enterprise(account, name, *, staff=None):
    """
    Create an organization with `account` as its first admin, and return it.

    A person creating their own needs a verified email and may create up to
    three. When staff create one for a customer (`staff` is the staff account,
    recorded as the creator), neither the verified email nor the cap is asked
    of the customer: staff have vouched for them.
    """
    name = _clean_name(name)
    with transaction.atomic():
        # Locking the account makes two "create" clicks take turns, so the cap holds.
        account = Account.objects.select_for_update().get(pk=account.pk)
        if not account.is_active or account.anonymised_at is not None:
            raise Refused("This account cannot have an organization.")
        if staff is None:
            if not accounts.has_verified_email(account):
                raise Refused("Verify your email address before creating an organization.")
            created = Enterprise.objects.filter(created_by=account).count()
            if created >= MAX_CREATED_PER_ACCOUNT:
                raise Refused(
                    f"You have created {created} organizations, which is the limit. "
                    "Contact us if you need more."
                )
        enterprise = _create_with_free_slug(name, created_by=staff or account)
        Membership.objects.create(
            account=account, enterprise=enterprise, role=Membership.Role.ADMIN
        )
        return enterprise


def _clean_name(name):
    name = " ".join(str(name or "").split())
    if len(name) < 2 or "\x00" in name:
        raise Refused("Enter the organization's name.")
    if len(name) > NAME_MAX_LENGTH:
        raise Refused(f"Enter a name of at most {NAME_MAX_LENGTH} characters.")
    return name


def _create_with_free_slug(name, created_by):
    """
    The slug is the name in address form ("Acme Ltd" gives acme-ltd). A second
    organization of the same name gets acme-ltd-2, and so on. A name with no
    letters the address can use (one written in another script) starts from
    "organization".
    """
    base = slugify(name)[:60].strip("-") or "organization"
    number = 1
    while True:
        slug = base if number == 1 else f"{base}-{number}"
        number += 1
        if slug in RESERVED_SLUGS or Enterprise.objects.filter(slug=slug).exists():
            continue
        try:
            # Its own savepoint: if another request took the slug this instant,
            # only this insert is undone and the loop tries the next one.
            with transaction.atomic():
                return Enterprise.objects.create(name=name, slug=slug, created_by=created_by)
        except IntegrityError:
            continue


# --- join codes ----------------------------------------------------------------


def create_code(admin_membership, max_uses, expires_at=None, tier=None):
    """
    Make a join code for the admin's organization. `max_uses` is how many people
    it lets in; it expires in 30 days unless another date is given. The tier is
    stored for Milestone 4 and means nothing yet.
    """
    if isinstance(max_uses, bool) or not isinstance(max_uses, int):
        raise Refused("Enter how many people may use the code, as a whole number.")
    if not 1 <= max_uses <= MAX_CODE_USES:
        raise Refused(f"Choose a number of uses from 1 to {MAX_CODE_USES:,}.")
    _check_tier(tier)
    now = timezone.now()
    if expires_at is None:
        expires_at = now + timedelta(days=DEFAULT_CODE_DAYS)
    elif expires_at <= now:
        raise Refused("Choose an expiry date in the future.")
    with transaction.atomic():
        admin = _acting_admin(admin_membership, admin_membership.enterprise_id)
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            try:
                with transaction.atomic():
                    return JoinCode.objects.create(
                        enterprise_id=admin.enterprise_id,
                        code=code,
                        tier=tier,
                        max_uses=max_uses,
                        expires_at=expires_at,
                        created_by_id=admin.account_id,
                    )
            except IntegrityError:
                continue  # the same ten characters already exist; draw again


def revoke_code(code, by=None):
    """Stop a join code working. Revoking twice keeps the first date."""
    with transaction.atomic():
        code = JoinCode.objects.select_for_update().get(pk=code.pk)
        if by is not None:
            _acting_admin(by, code.enterprise_id)
        if code.revoked_at is None:
            code.revoked_at = timezone.now()
            code.save(update_fields=["revoked_at"])
        return code


def redeem_code(code, account):
    """
    Join an organization with a code, and return the new membership.

    Refused, in this order, when: the code is unknown; the account already
    belongs (AlreadyMember) or was deactivated there; the code is revoked,
    expired or used up; or the organization has no places left.
    """
    typed = normalise_code(code)
    found = JoinCode.objects.filter(code=typed).first() if typed else None
    if found is None:
        raise Refused("That code is not valid. Check it and try again.")
    with transaction.atomic():
        _check_can_join(account)
        # The organization first (so the people limit cannot be passed by two
        # joins at once), then the code (so it cannot pass its cap).
        enterprise = Enterprise.objects.select_for_update().get(pk=found.enterprise_id)
        join_code = JoinCode.objects.select_for_update().get(pk=found.pk)
        existing = Membership.objects.filter(account=account, enterprise=enterprise).first()
        if existing is not None and existing.is_active:
            raise AlreadyMember(f"You are already a member of {enterprise.name}.")
        if existing is not None:
            raise Refused(
                f"Your membership of {enterprise.name} was deactivated, so a join code "
                "cannot be used. Ask one of its admins to reactivate you or send you an invite."
            )
        if join_code.revoked_at is not None:
            raise Refused("That code has been switched off. Ask the organization for a new one.")
        if join_code.expires_at <= timezone.now():
            raise Refused("That code has expired. Ask the organization for a new one.")
        if join_code.uses >= join_code.max_uses:
            raise Refused("That code has been used as many times as it allows.")
        if places_left(enterprise) < 1:
            raise Refused(
                f"{enterprise.name} cannot take more people at the moment. Ask one of its admins."
            )
        join_code.uses += 1
        join_code.save(update_fields=["uses"])
        return Membership.objects.create(
            account=account, enterprise=enterprise, joined_via_code=join_code
        )


# --- members -------------------------------------------------------------------


def deactivate_membership(membership, by=None):
    """
    The person has left: switch their membership off. They also stop being an
    admin, so they come back (if they do) as an ordinary member. The last active
    admin cannot be deactivated. Doing it twice changes nothing.
    """
    with transaction.atomic():
        membership = _locked(membership, by)
        if not membership.is_active:
            return membership
        _keep_one_admin(membership)
        membership.status = Membership.Status.DEACTIVATED
        membership.deactivated_at = timezone.now()
        membership.role = Membership.Role.MEMBER
        membership.save(update_fields=["status", "deactivated_at", "role"])
        return membership


def reactivate_membership(membership, by=None):
    """Switch a deactivated membership back on, as an ordinary member."""
    with transaction.atomic():
        membership = _locked(membership, by)
        if membership.is_active:
            return membership
        if membership.account.anonymised_at is not None:
            raise Refused("This member's account was erased, so it cannot be reactivated.")
        membership.status = Membership.Status.ACTIVE
        membership.deactivated_at = None
        membership.save(update_fields=["status", "deactivated_at"])
        return membership


def set_role(membership, role, by=None):
    """Make a member an admin, or an admin a member again (never the last admin)."""
    if role not in Membership.Role.values:
        raise Refused("The role must be member or admin.")
    with transaction.atomic():
        membership = _locked(membership, by)
        if not membership.is_active:
            raise Refused("Reactivate this member before changing their role.")
        if membership.role == role:
            return membership
        if role == Membership.Role.MEMBER:
            _keep_one_admin(membership)
        membership.role = role
        membership.save(update_fields=["role"])
        return membership


# --- helpers -------------------------------------------------------------------


def _check_tier(tier):
    if tier is None:
        return
    # bool is an int in Python; True must not pass as tier 1.
    if isinstance(tier, bool) or not isinstance(tier, int) or tier not in TIERS:
        raise Refused("The tier must be 1, 2 or 3.")


def _check_can_join(account):
    if not account.is_active or account.anonymised_at is not None:
        raise Refused("This account cannot join an organization.")
    if not accounts.has_verified_email(account):
        raise Refused("Verify your email address before joining an organization.")


def _acting_admin(by, enterprise_id):
    """
    The acting admin's membership as it is now, or Refused. Read again rather
    than trusted: they may have been demoted or deactivated since the page loaded.
    """
    current = Membership.objects.filter(
        pk=by.pk,
        enterprise_id=enterprise_id,
        role=Membership.Role.ADMIN,
        status=Membership.Status.ACTIVE,
    ).first()
    if current is None:
        raise Refused("Only an admin of this organization can do that.")
    return current


def _locked(membership, by):
    """
    Lock the organization, then the membership, and return the membership as it
    is now. Every change to a role or a status holds the organization's lock, so
    two admins acting on each other at the same moment take turns and "at least
    one admin" is counted on settled data.
    """
    Enterprise.objects.select_for_update().get(pk=membership.enterprise_id)
    locked = Membership.objects.select_for_update().get(pk=membership.pk)
    if by is not None:
        _acting_admin(by, locked.enterprise_id)
    return locked


def _keep_one_admin(membership):
    """Refuse if this is the organization's last active admin. The caller holds the lock."""
    if not membership.is_admin:
        return
    another = (
        Membership.objects.filter(
            enterprise_id=membership.enterprise_id,
            role=Membership.Role.ADMIN,
            status=Membership.Status.ACTIVE,
        )
        .exclude(pk=membership.pk)
        .exists()
    )
    if not another:
        raise Refused("An organization needs at least one admin. Make someone else an admin first.")
