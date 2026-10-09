"""
Every write to accounts and contact points goes through here.

Views stay thin: they call one of these functions and show the result. The rules
below (what may be primary, what may be removed, what counts as the same
address) are therefore in one place, whether the caller is a web page, a test
or an admin action.

Bad input raises django.core.exceptions.ValidationError, whose message a form
can show to a person. Typing an address that another account has verified is
allowed on purpose: anyone can type anything, and ownership is settled later,
by the verification click.

Every email also gets a row in allauth's EmailAddress table, written in the
same transaction as the ContactPoint. allauth resolves logins and password
resets through its table; ours is what matching and the profile page read.
Keeping both in step here means neither ever sees an address the other lacks.
"""

from allauth.account.models import EmailAddress
from allauth.core import context as allauth_context
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from .models import Account, ContactPoint
from .normalisers import normalise_email, normalise_phone


class EmailInUse(Exception):
    """
    The email is already some account's login name. Kept separate from
    ValidationError so the sign-up page can answer "check your inbox" either
    way and never reveal who has an account.
    """


def _clean_email(value: str) -> tuple[str, str]:
    """Return (as typed, normalised), or raise ValidationError."""
    typed = value.strip()
    validate_email(typed)
    return typed, normalise_email(typed)


def _lock(account: Account) -> None:
    """
    Hold a row lock on the account until the surrounding transaction ends, so
    two requests changing the same account's contacts take turns.
    """
    Account.objects.select_for_update().get(pk=account.pk)


def _locked_contact(account: Account, contact: ContactPoint) -> ContactPoint:
    """The contact's current state, locked, and only if it belongs to this account."""
    fresh = ContactPoint.objects.select_for_update().filter(pk=contact.pk, account=account).first()
    if fresh is None:
        raise ValidationError("That contact does not belong to this account.")
    return fresh


def register(email: str, phone: str, country: str | None, password: str, request=None) -> Account:
    """
    Create a person, an account and its two contact points in one transaction.
    Both contacts start unverified: the email is proven by the link this sends
    when given the request (a view passes it; a test may not); the phone by
    SMS, later. Raises EmailInUse if the address is already a login name, in
    any letter case, and ValidationError for a password Django's validators
    reject (too short, too common, too like the email, all digits).
    """
    typed, email_n = _clean_email(email)
    phone_n = normalise_phone(phone, country)
    if not password:
        raise ValidationError("A password is required.")
    # The unsaved Account only gives the similarity validator the email to compare.
    validate_password(password, user=Account(email=email_n))
    if Account.objects.filter(email__iexact=email_n).exists():
        raise EmailInUse(email_n)
    try:
        with transaction.atomic():
            # The manager makes the Person and the primary email contact too.
            account = Account.objects.create_user(email_n, password)
            account.contact_points.filter(kind=ContactPoint.Kind.EMAIL).update(value_display=typed)
            ContactPoint.objects.create(
                account=account,
                kind=ContactPoint.Kind.PHONE,
                value_normalised=phone_n,
                value_display=phone.strip(),
                is_primary=True,
            )
            EmailAddress.objects.create(user=account, email=email_n, primary=True)
    except IntegrityError:
        # Someone registered the same address between our check and our insert.
        raise EmailInUse(email_n) from None
    if request is not None:
        send_verification(request, account, email_n)
    return account


def send_verification(request, account: Account, email: str) -> None:
    """
    Email a verification link for one of the account's addresses. The link is
    signed, not stored, and expires after three days. The view that calls this
    is responsible for not letting it be hammered: allauth's own resend page is
    rate limited, this function is not.
    """
    address, _ = EmailAddress.objects.get_or_create(user=account, email=normalise_email(email))
    # allauth's mail code reads the request from this context (its middleware
    # sets it during a request; entering it again here is harmless) to build
    # the absolute link.
    with allauth_context.request_context(request):
        address.send_confirmation(request)


def account_for_reset(typed: str) -> Account | None:
    """
    The active account that has verified this address, or None. Only a verified
    contact point counts: an unverified address may sit on several accounts, and
    mailing a reset link to an address nobody has proven would hand the account
    to whoever typed it. The unique constraint on verified emails means there
    is at most one match.
    """
    contact = (
        ContactPoint.objects.select_related("account")
        .filter(
            kind=ContactPoint.Kind.EMAIL,
            value_normalised=normalise_email(typed),
            verified_at__isnull=False,
            account__is_active=True,
        )
        .first()
    )
    return contact.account if contact else None


def send_reset_notice(request, account: Account, typed: str) -> None:
    """
    Tell the account's other verified emails that a reset was requested. The
    notice has no link and no secret, so it is safe to send to an inbox we only
    half trust (an old work address, say): it just warns the owner.
    """
    from allauth.account.adapter import get_adapter

    typed_n = normalise_email(typed)
    others = account.contact_points.filter(
        kind=ContactPoint.Kind.EMAIL, verified_at__isnull=False
    ).exclude(value_normalised=typed_n)
    with allauth_context.request_context(request):
        for contact in others:
            get_adapter().send_mail(
                "account/email/password_reset_notice",
                contact.value_normalised,
                {"requested_for": typed_n},
            )


def add_email(account: Account, email: str) -> ContactPoint:
    """Add an unverified, non-primary email. The caller sends the verification link."""
    typed, email_n = _clean_email(email)
    try:
        with transaction.atomic():
            contact = ContactPoint.objects.create(
                account=account,
                kind=ContactPoint.Kind.EMAIL,
                value_normalised=email_n,
                value_display=typed,
            )
            EmailAddress.objects.create(user=account, email=email_n)
            return contact
    except IntegrityError:
        raise ValidationError("That email is already on your account.") from None


def make_primary(account: Account, contact: ContactPoint) -> None:
    """
    Make a verified email the account's primary, which is also its login name.
    The old primary stays on the account as an ordinary email.
    """
    with transaction.atomic():
        _lock(account)
        contact = _locked_contact(account, contact)
        if contact.kind != ContactPoint.Kind.EMAIL:
            raise ValidationError("Only an email can be the login address.")
        if contact.verified_at is None:
            raise ValidationError("Verify that email before making it your login address.")
        if contact.is_primary:
            return
        # Demote first: the database allows one primary per kind at any moment.
        account.contact_points.filter(kind=ContactPoint.Kind.EMAIL, is_primary=True).update(
            is_primary=False
        )
        contact.is_primary = True
        contact.save(update_fields=["is_primary"])
        account.email = contact.value_normalised
        try:
            account.save(update_fields=["email"])
        except IntegrityError:
            # Another account already uses this address as its login name.
            # Raising leaves the transaction, which undoes the demotion above.
            raise ValidationError(
                "Another account is using that address as its login name."
            ) from None
        # Same change in allauth's table, same order: demote, then promote.
        EmailAddress.objects.filter(user=account, primary=True).update(primary=False)
        EmailAddress.objects.update_or_create(
            user=account,
            email=contact.value_normalised,
            defaults={"primary": True, "verified": True},
        )


def remove_contact(account: Account, contact: ContactPoint) -> None:
    """
    Delete a contact point. A primary is never removed (not the login email,
    and not the phone, which can only be changed): make another email primary
    first, and the old one can then go.
    """
    with transaction.atomic():
        _lock(account)
        contact = _locked_contact(account, contact)
        if contact.is_primary:
            raise ValidationError("Make another email your login address before removing this one.")
        contact.delete()
        if contact.kind == ContactPoint.Kind.EMAIL:
            EmailAddress.objects.filter(user=account, email=contact.value_normalised).delete()


def change_phone(account: Account, phone: str, country: str | None) -> ContactPoint:
    """
    Set the account's one phone. A different number starts unverified; the same
    number keeps whatever verification it already had. Accounts that predate
    Milestone 1 (the superuser) have no phone, and this gives them their first.
    """
    phone_n = normalise_phone(phone, country)
    with transaction.atomic():
        _lock(account)
        current = (
            account.contact_points.select_for_update()
            .filter(kind=ContactPoint.Kind.PHONE, is_primary=True)
            .first()
        )
        if current is None:
            return ContactPoint.objects.create(
                account=account,
                kind=ContactPoint.Kind.PHONE,
                value_normalised=phone_n,
                value_display=phone.strip(),
                is_primary=True,
            )
        if current.value_normalised == phone_n:
            return current
        current.value_normalised = phone_n
        current.value_display = phone.strip()
        current.verified_at = None
        current.save(update_fields=["value_normalised", "value_display", "verified_at"])
        return current
