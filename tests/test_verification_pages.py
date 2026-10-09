"""
The pages a verification link opens say the right thing in each case, and
allauth's pages wear our layout.
"""

import pytest

from apps.accounts import services

from .test_verification import PASSWORD, fake_request, last_link


def names(response):
    return [t.name for t in response.templates]


@pytest.mark.django_db
def test_live_link_shows_the_address_and_a_confirm_button(client):
    services.register("bob@example.com", "+919876543210", None, PASSWORD, fake_request())
    response = client.get(last_link())
    assert response.status_code == 200
    assert "account/email_confirm.html" in names(response)
    assert "base.html" in names(response)  # our shell, via templates/allauth/layouts/base.html
    html = response.content.decode()
    assert "bob@example.com" in html and "<button" in html


@pytest.mark.django_db
def test_used_link_says_it_probably_already_worked(client):
    services.register("bob@example.com", "+919876543210", None, PASSWORD, fake_request())
    client.post(last_link())
    html = client.get(last_link()).content.decode()
    assert "no longer works" in html and "/accounts/login/" in html


@pytest.mark.django_db
def test_collision_page_offers_the_other_accounts_login_and_reset(client):
    first = services.register("a@example.com", "+919876543210", None, PASSWORD)
    second = services.register("b@example.com", "+14155552671", None, PASSWORD)
    services.add_email(first, "shared@example.com")
    services.send_verification(fake_request(), first, "shared@example.com")
    client.post(last_link())

    services.add_email(second, "shared@example.com")
    services.send_verification(fake_request(), second, "shared@example.com")
    html = client.get(last_link()).content.decode()
    assert "already verified on another account" in html
    assert "/accounts/login/" in html and "/accounts/password/reset/" in html


@pytest.mark.django_db
def test_verification_sent_page_and_mail_wording(client):
    services.register("bob@example.com", "+919876543210", None, PASSWORD, fake_request())
    from django.core import mail

    message = mail.outbox[0]
    assert message.subject == "[Accelerare] Confirm your email address"
    assert "Someone entered this email address on Accelerare" in message.body
    assert "testserver" not in message.body.replace(last_link(), "")  # no stray site name

    response = client.post("/accounts/login/", {"login": "bob@example.com", "password": PASSWORD})
    response = client.get(response["Location"])
    assert "account/verification_sent.html" in names(response)
    assert "Check your inbox" in response.content.decode()
