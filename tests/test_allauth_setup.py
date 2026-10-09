"""
allauth is wired in but its own signup page is closed; passwords use Argon2;
accounts that predate allauth get a row in its email table.
"""

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from .test_account_services import make_account


@pytest.mark.django_db
def test_new_passwords_are_hashed_with_argon2():
    account = make_account()
    assert account.password.startswith("argon2")
    assert account.check_password("a-long-test-password")


def test_allauth_signup_stays_closed():
    """/accounts/signup/ is our view now; allauth's own signup must still refuse to make accounts."""
    from apps.accounts.adapter import AccountAdapter

    assert AccountAdapter().is_open_for_signup(request=None) is False


def test_allauth_pages_are_mounted(client, db):
    assert client.get("/accounts/login/").status_code == 200
    assert client.get("/accounts/password/reset/").status_code == 200


def test_cache_table_works(db):
    """Rate limits count in the database cache; tests create the table themselves."""
    cache.set("probe", 1, 10)
    assert cache.get("probe") == 1


@pytest.mark.django_db(transaction=True)
def test_backfill_gives_existing_contacts_an_allauth_email_row():
    """
    Roll our app back to before 0004, create an account with a verified and an
    unverified email the old way, migrate forward, and check allauth's table.
    """
    executor = MigrationExecutor(connection)
    executor.migrate([("accounts", "0003_backfill_person_and_primary_email")])
    old = executor.loader.project_state(
        [("accounts", "0003_backfill_person_and_primary_email")]
    ).apps
    OldAccount = old.get_model("accounts", "Account")
    OldPerson = old.get_model("accounts", "Person")
    OldContact = old.get_model("accounts", "ContactPoint")
    account = OldAccount.objects.create(email="old@example.com", person=OldPerson.objects.create())
    OldContact.objects.create(
        account=account,
        kind="email",
        value_normalised="old@example.com",
        value_display="old@example.com",
        is_primary=True,
        verified_at=timezone.now(),
    )
    OldContact.objects.create(
        account=account,
        kind="email",
        value_normalised="second@example.com",
        value_display="second@example.com",
    )
    OldContact.objects.create(
        account=account, kind="phone", value_normalised="+919876543210", value_display="x"
    )

    executor = MigrationExecutor(connection)  # reload the graph after rolling back
    executor.migrate(executor.loader.graph.leaf_nodes())

    rows = {
        e.email: (e.primary, e.verified) for e in EmailAddress.objects.filter(user_id=account.pk)
    }
    assert rows == {"old@example.com": (True, True), "second@example.com": (False, False)}
