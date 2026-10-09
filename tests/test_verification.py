"""
Verification end to end, through allauth: register sends a link, the link
proves the address in both email tables, a used link is dead, and a second
account cannot verify an address the first has proven. Login honours the
verified flag of the exact address typed.
"""

import re

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.accounts import services
from apps.accounts.models import Account, ContactPoint, Person

PASSWORD = "a-long-test-password"


def fake_request():
    """Enough of a request for allauth to build a link and store a message."""
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    request.session = SessionStore()
    request._messages = FallbackStorage(request)
    return request


def last_link() -> str:
    body = mail.outbox[-1].body
    match = re.search(r"https?://\S+/accounts/confirm-email/\S+/", body)
    assert match, body
    return match.group(0)


def verify(client, account, email):
    """Send a link for `email` and click it the way a browser would."""
    services.send_verification(fake_request(), account, email)
    return client.post(last_link())


# --- register ----------------------------------------------------------------


@pytest.mark.django_db
def test_register_with_a_request_sends_the_link_and_mirrors_the_email():
    account = services.register("Bob@Example.com", "+919876543210", None, PASSWORD, fake_request())

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["bob@example.com"]
    assert message.subject.startswith("[Accelerare]")
    assert "/accounts/confirm-email/" in message.body

    row = EmailAddress.objects.get(user=account)
    assert (row.email, row.primary, row.verified) == ("bob@example.com", True, False)


@pytest.mark.django_db
def test_register_without_a_request_creates_the_rows_but_sends_nothing():
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    assert mail.outbox == []
    assert EmailAddress.objects.filter(user=account, primary=True, verified=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("password", ["password", "short", "12345678", "bob@example.com"])
def test_register_refuses_a_weak_password(password):
    with pytest.raises(ValidationError):
        services.register("bob@example.com", "+919876543210", None, password)
    assert (Account.objects.count(), Person.objects.count(), ContactPoint.objects.count()) == (
        0,
        0,
        0,
    )


# --- the link ----------------------------------------------------------------


@pytest.mark.django_db
def test_clicking_the_link_verifies_both_tables_and_a_second_click_is_harmless(client):
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)

    response = verify(client, account, "bob@example.com")
    assert response.status_code == 302

    contact = account.contact_points.get(kind=ContactPoint.Kind.EMAIL)
    first_proof = contact.verified_at
    assert first_proof is not None
    assert EmailAddress.objects.get(user=account).verified is True

    # Same link again: allauth no longer recognises it. Opening it shows the
    # "invalid link" page, submitting it is refused, and nothing changes.
    assert client.get(last_link()).status_code == 200
    assert client.post(last_link()).status_code == 404
    contact.refresh_from_db()
    assert contact.verified_at == first_proof


@pytest.mark.django_db
def test_second_account_cannot_verify_an_email_the_first_has_proven(client):
    first = services.register("a@example.com", "+919876543210", None, PASSWORD)
    second = services.register("b@example.com", "+14155552671", None, PASSWORD)
    services.add_email(first, "shared@example.com")
    assert verify(client, first, "shared@example.com").status_code == 302

    services.add_email(second, "shared@example.com")  # typing is allowed
    response = verify(client, second, "shared@example.com")

    shared_on_second = second.contact_points.get(value_normalised="shared@example.com")
    assert shared_on_second.verified_at is None
    assert EmailAddress.objects.get(user=second, email="shared@example.com").verified is False
    assert EmailAddress.objects.get(user=first, email="shared@example.com").verified is True
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("already confirmed by a different account" in m for m in messages), messages


# --- login -------------------------------------------------------------------


def login(client, email):
    client.logout()
    response = client.post("/accounts/login/", {"login": email, "password": PASSWORD})
    return response, "_auth_user_id" in client.session


@pytest.mark.django_db
def test_login_needs_the_exact_address_typed_to_be_verified(client):
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)

    # Unverified primary: not in, told to check the inbox.
    response, logged_in = login(client, "bob@example.com")
    assert not logged_in
    assert response.status_code == 302 and "confirm-email" in response["Location"]

    verify(client, account, "bob@example.com")
    _, logged_in = login(client, "bob@example.com")
    assert logged_in
    _, logged_in = login(client, "BOB@example.com")
    assert logged_in

    services.add_email(account, "second@example.com")
    verify(client, account, "second@example.com")
    _, logged_in = login(client, "second@example.com")
    assert logged_in

    services.add_email(account, "third@example.com")
    _, logged_in = login(client, "third@example.com")
    assert not logged_in


# --- the other services keep allauth's table in step --------------------------


@pytest.mark.django_db
def test_add_email_creates_an_unverified_allauth_row():
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    services.add_email(account, "Second@Example.com")
    row = EmailAddress.objects.get(user=account, email="second@example.com")
    assert (row.primary, row.verified) == (False, False)


@pytest.mark.django_db
def test_make_primary_moves_allauth_primary_too(client):
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    verify(client, account, "bob@example.com")
    second = services.add_email(account, "second@example.com")
    verify(client, account, "second@example.com")

    services.make_primary(account, second)

    account.refresh_from_db()
    assert account.email == "second@example.com"
    primaries = {e.email: e.primary for e in EmailAddress.objects.filter(user=account)}
    assert primaries == {"bob@example.com": False, "second@example.com": True}


@pytest.mark.django_db
def test_remove_contact_removes_the_allauth_row_as_well():
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    second = services.add_email(account, "second@example.com")
    services.remove_contact(account, second)
    assert not EmailAddress.objects.filter(user=account, email="second@example.com").exists()
    assert EmailAddress.objects.filter(user=account).count() == 1
