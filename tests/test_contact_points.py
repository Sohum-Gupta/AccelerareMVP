"""
Milestone 1, PR 1: Person, Account.person and ContactPoint.

These tests pin the three database rules and the manager behaviour that the
rest of Milestone 1 relies on:

1. A verified (kind, value) belongs to one account only.
2. An account cannot hold the same (kind, value) twice.
3. An account has at most one primary contact per kind.

Unverified duplicates across accounts are allowed on purpose: anyone can type
anyone's address into a form, and only the verification click settles ownership.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.accounts.models import ContactPoint, Person

Account = get_user_model()


def add_contact(account, value, *, kind=ContactPoint.Kind.EMAIL, verified=False, primary=False):
    return ContactPoint.objects.create(
        account=account,
        kind=kind,
        value_normalised=value,
        value_display=value,
        verified_at=timezone.now() if verified else None,
        is_primary=primary,
    )


@pytest.mark.django_db
def test_create_user_creates_person_and_primary_email_contact():
    account = Account.objects.create_user("Alice@Example.COM", "s3cret-pass")
    assert isinstance(account.person, Person)
    contact = account.contact_points.get()
    assert contact.kind == ContactPoint.Kind.EMAIL
    assert contact.value_normalised == "alice@example.com"
    assert contact.value_display == "Alice@Example.COM"
    assert contact.is_primary
    assert contact.verified_at is None  # proven only by clicking the link


@pytest.mark.django_db
def test_create_superuser_also_gets_person_and_contact():
    account = Account.objects.create_superuser("root@example.com", "s3cret-pass")
    assert account.person is not None
    assert account.contact_points.filter(is_primary=True).count() == 1


@pytest.mark.django_db
def test_each_account_gets_its_own_person():
    a = Account.objects.create_user("a@example.com", "x")
    b = Account.objects.create_user("b@example.com", "x")
    assert a.person != b.person


@pytest.mark.django_db
def test_verified_contact_has_one_owner():
    a = Account.objects.create_user("a@example.com", "x")
    b = Account.objects.create_user("b@example.com", "x")
    add_contact(a, "shared@example.com", verified=True)
    with pytest.raises(IntegrityError):
        add_contact(b, "shared@example.com", verified=True)


@pytest.mark.django_db
def test_unverified_duplicates_across_accounts_are_allowed():
    a = Account.objects.create_user("a@example.com", "x")
    b = Account.objects.create_user("b@example.com", "x")
    add_contact(a, "shared@example.com")
    add_contact(b, "shared@example.com")
    assert ContactPoint.objects.filter(value_normalised="shared@example.com").count() == 2


@pytest.mark.django_db
def test_one_verified_and_one_unverified_copy_are_allowed():
    a = Account.objects.create_user("a@example.com", "x")
    b = Account.objects.create_user("b@example.com", "x")
    add_contact(a, "shared@example.com", verified=True)
    add_contact(b, "shared@example.com")  # b typed it; has not proven it


@pytest.mark.django_db
def test_same_value_with_different_kinds_never_collides():
    a = Account.objects.create_user("a@example.com", "x")
    b = Account.objects.create_user("b@example.com", "x")
    add_contact(a, "+919876543210", kind=ContactPoint.Kind.PHONE, verified=True)
    add_contact(b, "+919876543210", kind=ContactPoint.Kind.EMAIL, verified=True)


@pytest.mark.django_db
def test_account_cannot_hold_the_same_contact_twice():
    a = Account.objects.create_user("a@example.com", "x")
    add_contact(a, "second@example.com")
    with pytest.raises(IntegrityError):
        add_contact(a, "second@example.com")


@pytest.mark.django_db
def test_at_most_one_primary_per_kind():
    a = Account.objects.create_user("a@example.com", "x")  # already has a primary email
    with pytest.raises(IntegrityError):
        add_contact(a, "second@example.com", primary=True)


@pytest.mark.django_db
def test_primary_phone_and_primary_email_can_coexist():
    a = Account.objects.create_user("a@example.com", "x")
    add_contact(a, "+919876543210", kind=ContactPoint.Kind.PHONE, primary=True)
    assert a.contact_points.filter(is_primary=True).count() == 2


@pytest.mark.django_db
def test_person_cannot_be_deleted_while_an_account_points_at_it():
    a = Account.objects.create_user("a@example.com", "x")
    with pytest.raises(IntegrityError), transaction.atomic():
        a.person.delete()


@pytest.mark.django_db(transaction=True)
def test_backfill_gives_existing_accounts_a_person_and_a_contact():
    """
    Production already has an account created before Person existed. Roll the
    accounts app back to 0001, create such an account, migrate forward, and
    check the data migration filled in what the new code expects.
    """
    executor = MigrationExecutor(connection)
    executor.migrate([("accounts", "0001_initial")])
    OldAccount = executor.loader.project_state([("accounts", "0001_initial")]).apps.get_model(
        "accounts", "Account"
    )
    OldAccount.objects.create(email="Old@Example.com", password="!", is_staff=True)

    executor = MigrationExecutor(connection)  # reload the graph after rolling back
    executor.migrate(executor.loader.graph.leaf_nodes())

    account = Account.objects.get(email="Old@Example.com")
    assert account.person is not None
    contact = account.contact_points.get()
    assert contact.kind == ContactPoint.Kind.EMAIL
    assert contact.value_normalised == "old@example.com"
    assert contact.value_display == "Old@Example.com"
    assert contact.is_primary and contact.verified_at is None
