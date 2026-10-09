"""
Milestone 1, PR 2: the rules for writing accounts and contact points.

Every write goes through apps/accounts/services.py. These tests exercise the
services directly, with no views, so a rule that breaks fails here first.

Two conventions the tests rely on:
- Bad input raises django.core.exceptions.ValidationError, whose messages a
  form can show to a person.
- Typing an address that another account has verified is allowed (anyone can
  type anything). Ownership is settled later, by the verification click.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import ContactPoint, Person

Account = get_user_model()


def verify(contact):
    contact.verified_at = timezone.now()
    contact.save(update_fields=["verified_at"])
    return contact


def make_account(email="bob@example.com", phone="+919876543210"):
    return services.register(email, phone, None, "a-long-test-password")


# --- normalise_phone ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "country", "expected"),
    [
        ("098765 43210", "IN", "+919876543210"),  # leading zero and a space
        ("+91 98765 43210", "IN", "+919876543210"),  # same number, typed in full
        ("(415) 555-2671", "US", "+14155552671"),
        ("020 7946 0958", "GB", "+442079460958"),
        ("+44 20 7946 0958", "IN", "+442079460958"),  # a leading + beats the selector
        ("+44 20 7946 0958", None, "+442079460958"),  # and needs no country at all
    ],
)
def test_normalise_phone_gives_one_international_form(raw, country, expected):
    assert services.normalise_phone(raw, country) == expected


@pytest.mark.parametrize(
    ("raw", "country"),
    [
        ("123", "IN"),  # parses, but is not a real number
        ("", "IN"),  # nothing to parse
        ("not a number", "IN"),
        ("98765 43210", None),  # no country and no leading +
        ("98765 43210", "ZZ"),  # not a country
    ],
)
def test_normalise_phone_rejects_bad_input(raw, country):
    with pytest.raises(ValidationError):
        services.normalise_phone(raw, country)


def test_normalise_email_lowercases_and_trims_only():
    assert services.normalise_email("  Bob.Smith+Work@Example.COM ") == "bob.smith+work@example.com"


# --- register ----------------------------------------------------------------


@pytest.mark.django_db
def test_register_creates_person_account_and_two_primary_contacts():
    account = services.register("Bob@Example.com", "098765 43210", "IN", "a-long-test-password")

    assert Person.objects.count() == 1
    assert account.person is not None
    assert account.email == "bob@example.com"  # the login name is always the normalised form
    assert account.check_password("a-long-test-password")

    email = account.contact_points.get(kind=ContactPoint.Kind.EMAIL)
    assert (email.value_normalised, email.value_display) == ("bob@example.com", "Bob@Example.com")
    assert email.is_primary and email.verified_at is None  # proven only by the link

    phone = account.contact_points.get(kind=ContactPoint.Kind.PHONE)
    assert (phone.value_normalised, phone.value_display) == ("+919876543210", "+91 98765 43210")
    assert phone.is_primary and phone.verified_at is None  # SMS verification comes later

    assert account.contact_points.count() == 2


@pytest.mark.django_db
def test_register_refuses_an_email_already_used_as_a_login_name_in_any_case():
    make_account("bob@example.com")
    with pytest.raises(services.EmailInUse):
        services.register("BOB@example.com", "+14155552671", None, "a-long-test-password")
    assert Account.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("email", "phone"),
    [("not-an-email", "+919876543210"), ("bob@example.com", "123")],
)
def test_register_with_bad_input_creates_nothing(email, phone):
    with pytest.raises(ValidationError):
        services.register(email, phone, "IN", "a-long-test-password")
    assert (Account.objects.count(), Person.objects.count(), ContactPoint.objects.count()) == (
        0,
        0,
        0,
    )


@pytest.mark.django_db
def test_register_needs_a_password():
    with pytest.raises(ValidationError):
        services.register("bob@example.com", "+919876543210", None, "")
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_register_allows_an_email_another_account_has_verified():
    """Typing is not owning: the collision is settled at the verification click."""
    a = make_account("a@example.com", "+919876543210")
    add = services.add_email(a, "shared@example.com")
    verify(add)
    b = services.register("shared@example.com", "+14155552671", None, "a-long-test-password")
    assert b.contact_points.get(kind=ContactPoint.Kind.EMAIL).verified_at is None


@pytest.mark.django_db
def test_register_allows_the_same_phone_on_two_accounts():
    make_account("a@example.com", "+919876543210")
    make_account("b@example.com", "+919876543210")
    assert ContactPoint.objects.filter(value_normalised="+919876543210").count() == 2


# --- add_email ---------------------------------------------------------------


@pytest.mark.django_db
def test_add_email_creates_an_unverified_non_primary_contact():
    account = make_account()
    contact = services.add_email(account, " Personal@Gmail.com ")
    assert contact.kind == ContactPoint.Kind.EMAIL
    assert (contact.value_normalised, contact.value_display) == (
        "personal@gmail.com",
        "Personal@Gmail.com",
    )
    assert contact.verified_at is None and not contact.is_primary
    assert contact.account == account


@pytest.mark.django_db
def test_add_email_refuses_a_duplicate_on_the_same_account_in_any_case():
    account = make_account("bob@example.com")
    with pytest.raises(ValidationError):
        services.add_email(account, "BOB@example.com")  # that is already the primary
    services.add_email(account, "other@example.com")
    with pytest.raises(ValidationError):
        services.add_email(account, "Other@Example.com")
    assert account.contact_points.filter(kind=ContactPoint.Kind.EMAIL).count() == 2


@pytest.mark.django_db
def test_add_email_refuses_an_invalid_address():
    account = make_account()
    with pytest.raises(ValidationError):
        services.add_email(account, "nope")


@pytest.mark.django_db
def test_add_email_allows_an_address_another_account_has_verified():
    a = make_account("a@example.com", "+919876543210")
    verify(services.add_email(a, "shared@example.com"))
    b = make_account("b@example.com", "+14155552671")
    contact = services.add_email(b, "shared@example.com")
    assert contact.verified_at is None  # b has typed it, not proven it


# --- make_primary ------------------------------------------------------------


@pytest.mark.django_db
def test_make_primary_changes_the_login_name_and_demotes_the_old_primary():
    account = make_account("amazon@example.com")
    verify(account.contact_points.get(value_normalised="amazon@example.com"))
    personal = verify(services.add_email(account, "personal@example.com"))

    services.make_primary(account, personal)

    account.refresh_from_db()
    assert account.email == "personal@example.com"
    primaries = account.contact_points.filter(kind=ContactPoint.Kind.EMAIL, is_primary=True)
    assert [c.value_normalised for c in primaries] == ["personal@example.com"]
    assert account.contact_points.filter(value_normalised="amazon@example.com").exists()


@pytest.mark.django_db
def test_make_primary_on_the_current_primary_changes_nothing():
    account = make_account("bob@example.com")
    primary = verify(account.contact_points.get(value_normalised="bob@example.com"))
    services.make_primary(account, primary)
    account.refresh_from_db()
    assert account.email == "bob@example.com"
    assert account.contact_points.filter(is_primary=True, kind=ContactPoint.Kind.EMAIL).count() == 1


@pytest.mark.django_db
def test_make_primary_refuses_an_unverified_email():
    account = make_account()
    unverified = services.add_email(account, "personal@example.com")
    with pytest.raises(ValidationError):
        services.make_primary(account, unverified)
    account.refresh_from_db()
    assert account.email == "bob@example.com"


@pytest.mark.django_db
def test_make_primary_refuses_another_accounts_contact_and_phones():
    a = make_account("a@example.com", "+919876543210")
    b = make_account("b@example.com", "+14155552671")
    theirs = verify(b.contact_points.get(value_normalised="b@example.com"))
    with pytest.raises(ValidationError):
        services.make_primary(a, theirs)
    with pytest.raises(ValidationError):
        services.make_primary(a, verify(a.contact_points.get(kind=ContactPoint.Kind.PHONE)))


@pytest.mark.django_db
def test_make_primary_refuses_when_another_account_uses_the_address_as_its_login_name():
    """
    a has verified shared@; b registered with shared@ but never proved it, so it
    is b's login name. Two accounts cannot share a login name, so a is refused
    and nothing changes. (Rare edge; the collision flow in PR 3 will explain it.)
    """
    a = make_account("a@example.com", "+919876543210")
    verify(a.contact_points.get(value_normalised="a@example.com"))
    shared = verify(services.add_email(a, "shared@example.com"))
    make_account("shared@example.com", "+14155552671")

    with pytest.raises(ValidationError):
        services.make_primary(a, shared)

    a.refresh_from_db()
    assert a.email == "a@example.com"
    assert a.contact_points.get(is_primary=True, kind=ContactPoint.Kind.EMAIL).value_normalised == (
        "a@example.com"
    )


# --- remove_contact ----------------------------------------------------------


@pytest.mark.django_db
def test_remove_contact_deletes_a_non_primary_email():
    account = make_account()
    extra = services.add_email(account, "extra@example.com")
    services.remove_contact(account, extra)
    assert not account.contact_points.filter(value_normalised="extra@example.com").exists()


@pytest.mark.django_db
def test_remove_contact_refuses_the_primary_email_and_the_phone():
    account = make_account()
    with pytest.raises(ValidationError):
        services.remove_contact(account, account.contact_points.get(kind=ContactPoint.Kind.EMAIL))
    with pytest.raises(ValidationError):
        services.remove_contact(account, account.contact_points.get(kind=ContactPoint.Kind.PHONE))
    assert account.contact_points.count() == 2


@pytest.mark.django_db
def test_remove_contact_refuses_another_accounts_contact():
    a = make_account("a@example.com", "+919876543210")
    b = make_account("b@example.com", "+14155552671")
    extra = services.add_email(b, "extra@example.com")
    with pytest.raises(ValidationError):
        services.remove_contact(a, extra)
    assert ContactPoint.objects.filter(pk=extra.pk).exists()


@pytest.mark.django_db
def test_an_old_primary_can_be_removed_once_another_email_is_primary():
    account = make_account("amazon@example.com")
    old = verify(account.contact_points.get(value_normalised="amazon@example.com"))
    personal = verify(services.add_email(account, "personal@example.com"))
    services.make_primary(account, personal)
    old.refresh_from_db()
    services.remove_contact(account, old)
    assert [c.value_normalised for c in account.contact_points.filter(kind="email")] == [
        "personal@example.com"
    ]


# --- change_phone ------------------------------------------------------------


@pytest.mark.django_db
def test_change_phone_replaces_the_number_and_resets_verification():
    account = make_account(phone="+919876543210")
    phone = account.contact_points.get(kind=ContactPoint.Kind.PHONE)
    verify(phone)

    services.change_phone(account, "(415) 555-2671", "US")

    phone.refresh_from_db()
    assert phone.value_normalised == "+14155552671"
    assert phone.value_display == "+1 415-555-2671"
    assert phone.is_primary and phone.verified_at is None  # a new number is unproven
    assert account.contact_points.filter(kind=ContactPoint.Kind.PHONE).count() == 1


@pytest.mark.django_db
def test_change_phone_to_the_same_number_keeps_its_verification():
    account = make_account(phone="+919876543210")
    phone = verify(account.contact_points.get(kind=ContactPoint.Kind.PHONE))
    services.change_phone(account, "098765 43210", "IN")
    phone.refresh_from_db()
    assert phone.verified_at is not None


@pytest.mark.django_db
def test_change_phone_gives_a_phoneless_account_its_first_phone():
    """Accounts that predate Milestone 1 (the superuser) have no phone yet."""
    account = Account.objects.create_superuser("root@example.com", "a-long-test-password")
    assert not account.contact_points.filter(kind=ContactPoint.Kind.PHONE).exists()
    services.change_phone(account, "+44 20 7946 0958", None)
    phone = account.contact_points.get(kind=ContactPoint.Kind.PHONE)
    assert phone.value_normalised == "+442079460958" and phone.is_primary


@pytest.mark.django_db
def test_change_phone_with_a_bad_number_changes_nothing():
    account = make_account(phone="+919876543210")
    with pytest.raises(ValidationError):
        services.change_phone(account, "123", "IN")
    assert account.contact_points.get(kind=ContactPoint.Kind.PHONE).value_normalised == (
        "+919876543210"
    )
