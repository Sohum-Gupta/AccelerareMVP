"""
Every write to an organization goes through here: creating one, join codes,
invites, roles, deactivating and reactivating. Views and the staff admin stay thin: they
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
* Deactivating someone deletes their unfinished survey attempt for the
  organization. Their licence stays with the membership and works again when
  they are reactivated; what they have submitted stays.
* A join code works until it is revoked, expires or runs out of uses. A
  deactivated member cannot come back with a code; an admin reactivates them.
* An invite goes to one email address, works once and lasts 14 days. Only an
  account that has verified that address can accept it; the link by itself
  proves nothing, so a forwarded link is useless to anyone else. An invite
  brings a deactivated member back. If the email cannot be sent, the invite is
  kept and the admin can copy the link.

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

import logging
import secrets
from datetime import timedelta
from smtplib import SMTPException

from allauth.account.adapter import get_adapter
from allauth.core import context as allauth_context
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts import services as accounts
from apps.accounts.adapter import describe_mail_error
from apps.accounts.models import Account, ContactPoint
from apps.accounts.normalisers import normalise_email

from .models import Enterprise, Invite, JoinCode, Membership

logger = logging.getLogger(__name__)

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
INVITE_DAYS = 14
TIERS = (1, 2, 3)


class Refused(Exception):
    """An action the rules do not allow. str(error) is plain words for the person."""


class AlreadyMember(Refused):
    """
    The account already belongs to the organization. `enterprise` is that
    organization, so the page can simply take them there.
    """

    def __init__(self, enterprise):
        super().__init__(f"You are already a member of {enterprise.name}.")
        self.enterprise = enterprise


class WrongAddress(Refused):
    """The invite went to an address this account has not verified (the page links to the profile)."""


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
    found = _find_code(code)
    with transaction.atomic():
        _check_can_join(account)
        # The organization first (so the people limit cannot be passed by two
        # joins at once), then the code (so it cannot pass its cap).
        enterprise = Enterprise.objects.select_for_update().get(pk=found.enterprise_id)
        join_code = JoinCode.objects.select_for_update().get(pk=found.pk)
        _check_code_lets_in(join_code, enterprise, account)
        join_code.uses += 1
        join_code.save(update_fields=["uses"])
        return Membership.objects.create(
            account=account, enterprise=enterprise, joined_via_code=join_code
        )


def check_code(code, account):
    """
    What redeem_code would answer, without joining: the join code (its
    `enterprise` is the organization) if it would let this account in, or the
    same refusal. The join page calls this first, so the person reads what
    joining means before anything is written.

    Nothing is locked or changed here. redeem_code makes every check again,
    under its locks, when the person confirms: things may have changed since.
    """
    found = _find_code(code)
    _check_can_join(account)
    _check_code_lets_in(found, found.enterprise, account)
    return found


def _find_code(code):
    typed = normalise_code(code)
    found = JoinCode.objects.select_related("enterprise").filter(code=typed).first()
    if not typed or found is None:
        raise Refused("That code is not valid. Check it and try again.")
    return found


def _check_code_lets_in(join_code, enterprise, account):
    """The rules of joining by code, in the order the person is told about them."""
    existing = Membership.objects.filter(account=account, enterprise=enterprise).first()
    if existing is not None and existing.is_active:
        raise AlreadyMember(enterprise)
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


# --- invites -------------------------------------------------------------------


def invite_by_email(admin_membership, email, tier=None, *, request=None):
    """
    Invite one email address to the admin's organization. Returns (invite, sent).

    Refused when the address is not an address, already belongs to an active
    member, or already has an open invite, and when the organization has no
    places left. The invite uses a place from the moment it exists, whatever
    becomes of it.

    The email goes out after the invite is saved, and only when a request is
    given (a view passes it; it is what the link's address is built from).
    `sent` is False if the mail server refused or nothing was sent; the invite
    is kept either way, and the admin can copy its link (`invite_link`).
    """
    typed = str(email or "").strip()
    try:
        validate_email(typed)
    except ValidationError:
        raise Refused("Enter a valid email address.") from None
    address = normalise_email(typed)
    _check_tier(tier)
    with transaction.atomic():
        # The organization's lock makes two invites take turns, so the count of
        # places and the "one open invite per address" check see settled data.
        enterprise = Enterprise.objects.select_for_update().get(pk=admin_membership.enterprise_id)
        admin = _acting_admin(admin_membership, enterprise.pk)
        now = timezone.now()
        if _active_member_has_verified(enterprise, address):
            raise Refused("Someone with that address is already a member.")
        if _open_invites(enterprise, now).filter(email=address).exists():
            raise Refused(
                "There is already an open invite to that address. "
                "Revoke it first if you want to send a new one."
            )
        if places_left(enterprise) < 1:
            raise Refused(f"{enterprise.name} has no places left. Contact us to add more.")
        invite = Invite.objects.create(
            enterprise=enterprise,
            email=address,
            token=secrets.token_urlsafe(32),
            tier=tier,
            expires_at=now + timedelta(days=INVITE_DAYS),
            created_by_id=admin.account_id,
        )
    sent = send_invite_email(invite, request) if request is not None else False
    return invite, sent


def invite_link(invite, request):
    """The full address of the page where this invite is accepted."""
    return request.build_absolute_uri(reverse("join_invite", args=[invite.token]))


def send_invite_email(invite, request):
    """
    Email the invite's link to its address. True if the mail server took it.
    A refusal (Amazon SES refuses unverified addresses while it is in its
    sandbox) or an outage is logged without the address and reported as False,
    never raised: the invite is already saved.
    """
    context = {
        "enterprise_name": invite.enterprise.name,
        "invite_url": invite_link(invite, request),
        "days": INVITE_DAYS,
    }
    # allauth's adapter renders the mail, so the subject prefix and the From
    # address are the same as on every other email the site sends.
    with allauth_context.request_context(request):
        message = get_adapter().render_mail("enterprises/email/invite", invite.email, context)
        try:
            message.send()
        except (SMTPException, OSError) as error:
            logger.error("Could not send an invite email (%s)", describe_mail_error(error))
            return False
    return True


def revoke_invite(invite, by=None):
    """
    Withdraw an invite that has not been accepted. Revoking twice keeps the
    first date. It still counts towards the people limit.
    """
    with transaction.atomic():
        invite = Invite.objects.select_for_update().get(pk=invite.pk)
        if by is not None:
            _acting_admin(by, invite.enterprise_id)
        if invite.accepted_at is not None:
            raise Refused("That invite has already been accepted.")
        if invite.revoked_at is None:
            invite.revoked_at = timezone.now()
            invite.save(update_fields=["revoked_at"])
        return invite


def accept_invite(token, account):
    """
    Join an organization with an invite link, and return the membership.

    Refused, in this order, when: the link is unknown; the account already
    belongs (AlreadyMember); the invite was withdrawn, already used or has
    expired; or the account has not verified the address the invite was sent to
    (WrongAddress). A deactivated member is brought back, as an ordinary member.
    Accepting needs no free place: the invite took its place when it was sent.
    """
    found = _find_invite(token)
    with transaction.atomic():
        _check_can_join(account)
        enterprise = Enterprise.objects.select_for_update().get(pk=found.enterprise_id)
        invite = Invite.objects.select_for_update().get(pk=found.pk)
        existing = _check_invite_lets_in(invite, enterprise, account)
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])
        if existing is None:
            return Membership.objects.create(
                account=account, enterprise=enterprise, joined_via_invite=invite
            )
        # A deactivated member coming back. The invite is now how they got in.
        existing.status = Membership.Status.ACTIVE
        existing.deactivated_at = None
        existing.joined_via_invite = invite
        existing.joined_via_code = None
        existing.save(
            update_fields=["status", "deactivated_at", "joined_via_invite", "joined_via_code"]
        )
        return existing


def check_invite(token, account):
    """
    What accept_invite would answer, without joining: the invite (its
    `enterprise` is the organization) if this account could accept it, or the
    same refusal. For the join page, like check_code: nothing is locked or
    changed, and accept_invite checks again when the person confirms.
    """
    found = _find_invite(token)
    _check_can_join(account)
    _check_invite_lets_in(found, found.enterprise, account)
    return found


def _find_invite(token):
    found = Invite.objects.select_related("enterprise").filter(token=str(token or "")).first()
    if found is None:
        raise Refused("That invite link is not valid.")
    return found


def _check_invite_lets_in(invite, enterprise, account):
    """
    The rules of accepting an invite, in the order the person is told about
    them. Returns the account's deactivated membership if it has one (the
    invite brings it back), else None.
    """
    existing = Membership.objects.filter(account=account, enterprise=enterprise).first()
    if existing is not None and existing.is_active:
        raise AlreadyMember(enterprise)
    if invite.revoked_at is not None:
        raise Refused("That invite has been withdrawn. Ask the organization to send a new one.")
    if invite.accepted_at is not None:
        raise Refused("That invite has already been used.")
    if invite.expires_at <= timezone.now():
        raise Refused("That invite has expired. Ask the organization to send a new one.")
    if not invite.email:
        # The person it was sent to has been erased, and the address with them.
        raise Refused("That invite link is not valid.")
    if not _has_verified(account, invite.email):
        raise WrongAddress(
            f"This invite was sent to {invite.email}. Log in with that address, "
            "or add and verify it on your profile, then open the link again."
        )
    return existing


# --- members -------------------------------------------------------------------


def deactivate_membership(membership, by=None):
    """
    The person has left: switch their membership off. They also stop being an
    admin, so they come back (if they do) as an ordinary member. The last active
    admin cannot be deactivated. Doing it twice changes nothing.

    Their unfinished survey attempt for this organization is deleted: it could
    not be continued, and it would be in the way if they came back. The licence
    it was on stays with the membership, unused again, and works once they are
    reactivated. Surveys they have submitted, and anything they took personally,
    are left alone. The returned membership's `draft_deleted` says whether an
    attempt was deleted, so the page or the admin can say so.
    """
    with transaction.atomic():
        membership = _locked(membership, by)
        membership.draft_deleted = False
        if not membership.is_active:
            return membership
        _keep_one_admin(membership)
        membership.status = Membership.Status.DEACTIVATED
        membership.deactivated_at = timezone.now()
        membership.role = Membership.Role.MEMBER
        membership.save(update_fields=["status", "deactivated_at", "role"])
        # Through the reverse name: this app never imports the responses app.
        # Starting an attempt locks this same membership row first, so a start
        # and a deactivation take turns and no draft can slip past this delete.
        deleted, _ = membership.responses.filter(status="draft").delete()
        membership.draft_deleted = deleted > 0
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


def _has_verified(account, address):
    return account.contact_points.filter(
        kind=ContactPoint.Kind.EMAIL, value_normalised=address, verified_at__isnull=False
    ).exists()


def _active_member_has_verified(enterprise, address):
    """True if an active member of this organization has proven the address is theirs."""
    return ContactPoint.objects.filter(
        kind=ContactPoint.Kind.EMAIL,
        value_normalised=address,
        verified_at__isnull=False,
        # One filter call, so both conditions are about the same membership.
        account__memberships__enterprise=enterprise,
        account__memberships__status=Membership.Status.ACTIVE,
    ).exists()


def _open_invites(enterprise, now):
    """Invites that could still be accepted: not used, not withdrawn, not expired."""
    return enterprise.invites.filter(
        accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now
    )


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
