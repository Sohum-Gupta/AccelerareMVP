"""
Password reset: the link goes only to a verified address, the page never says
whether an account exists, other verified emails get a link-free notice, and
the link really changes the password.
"""

import re

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import Account

from .test_verification import PASSWORD, fake_request, verify

NEW_PASSWORD = "another-long-test-password"


def reset_link() -> str:
    match = re.search(r"https?://\S+/accounts/password/reset/key/\S+/", mail.outbox[-1].body)
    assert match, mail.outbox[-1].body
    return match.group(0)


def make_account(client, email="bob@example.com"):
    account = services.register(email, "+919876543210", None, PASSWORD, fake_request())
    verify(client, account, email)
    mail.outbox.clear()
    return account


def request_reset(client, email):
    return client.post(reverse("account_reset_password"), {"email": email}, follow=True)


@pytest.mark.django_db
def test_verified_address_gets_a_link_and_the_neutral_page(client):
    make_account(client)
    response = request_reset(client, "Bob@Example.com")
    assert "If an account exists" in response.content.decode()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["bob@example.com"]
    assert "/accounts/password/reset/key/" in mail.outbox[0].body


@pytest.mark.django_db
def test_unknown_address_gets_the_same_page_and_no_mail(client):
    known = request_reset(client, "nobody@example.com")
    assert "If an account exists" in known.content.decode()
    assert mail.outbox == []


@pytest.mark.django_db
def test_unverified_address_gets_no_link(client):
    account = make_account(client)
    services.add_email(account, "second@example.com")  # never verified
    response = request_reset(client, "second@example.com")
    assert "If an account exists" in response.content.decode()
    assert mail.outbox == []


@pytest.mark.django_db
def test_second_verified_email_resets_and_others_get_a_notice_without_a_link(client):
    account = make_account(client)
    services.add_email(account, "personal@example.com")
    verify(client, account, "personal@example.com")
    mail.outbox.clear()

    request_reset(client, "personal@example.com")
    by_recipient = {m.to[0]: m for m in mail.outbox}
    assert set(by_recipient) == {"personal@example.com", "bob@example.com"}
    assert "/password/reset/key/" in by_recipient["personal@example.com"].body
    notice = by_recipient["bob@example.com"]
    assert "/password/reset/key/" not in notice.body and "http" not in notice.body
    assert "personal@example.com" in notice.body


@pytest.mark.django_db
def test_single_verified_email_sends_one_mail_only(client):
    make_account(client)
    request_reset(client, "bob@example.com")
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_unverified_other_email_gets_no_notice(client):
    account = make_account(client)
    services.add_email(account, "pending@example.com")
    request_reset(client, "bob@example.com")
    assert [m.to[0] for m in mail.outbox] == ["bob@example.com"]


@pytest.mark.django_db
def test_full_flow_sets_the_new_password(client):
    make_account(client)
    request_reset(client, "bob@example.com")
    link = reset_link()

    page = client.get(link, follow=True)
    assert "Choose a new password" in page.content.decode()
    done = client.post(
        page.request["PATH_INFO"],
        {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
        follow=True,
    )
    assert "Password changed" in done.content.decode()

    account = Account.objects.get(email="bob@example.com")
    assert account.check_password(NEW_PASSWORD)
    assert not account.check_password(PASSWORD)
    client.logout()
    assert (
        client.login(email="bob@example.com", password=NEW_PASSWORD)
        or client.post(
            reverse("account_login"), {"login": "bob@example.com", "password": NEW_PASSWORD}
        ).status_code
        == 302
    )


@pytest.mark.django_db
def test_used_link_shows_the_friendly_page(client):
    make_account(client)
    request_reset(client, "bob@example.com")
    link = reset_link()
    page = client.get(link, follow=True)
    client.post(
        page.request["PATH_INFO"],
        {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )
    again = client.get(link, follow=True).content.decode()
    assert "no longer works" in again


@pytest.mark.django_db
def test_garbage_link_shows_the_friendly_page(client):
    response = client.get("/accounts/password/reset/key/zz-notarealtoken/")
    assert "no longer works" in response.content.decode()


@pytest.mark.django_db
def test_request_page_renders_in_our_layout(client):
    response = client.get(reverse("account_reset_password"))
    names = [t.name for t in response.templates]
    assert "account/password_reset.html" in names and "base.html" in names
    assert "includes/field.html" in names


@pytest.mark.django_db
def test_reset_requests_are_rate_limited(client):
    make_account(client)
    for _ in range(10):
        request_reset(client, "bob@example.com")
    # allauth allows 5 per minute per address; the rest are refused, not mailed.
    assert len(mail.outbox) == 5
