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
"""

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


def register(email: str, phone: str, country: str | None, password: str) -> Account:
    """
    Create a person, an account and its two contact points in one transaction.
    Both contacts start unverified: the email is proven by the link we send
    (PR 3); the phone by SMS, later. Raises EmailInUse if the address is
    already a login name, in any letter case.
    """
    typed, email_n = _clean_email(email)
    phone_n = normalise_phone(phone, country)
    if not password:
        raise ValidationError("A password is required.")
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
    except IntegrityError:
        # Someone registered the same address between our check and our insert.
        raise EmailInUse(email_n) from None
    return account


def add_email(account: Account, email: str) -> ContactPoint:
    """Add an unverified, non-primary email. The caller sends the verification link."""
    typed, email_n = _clean_email(email)
    try:
        with transaction.atomic():
            return ContactPoint.objects.create(
                account=account,
                kind=ContactPoint.Kind.EMAIL,
                value_normalised=email_n,
                value_display=typed,
            )
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
