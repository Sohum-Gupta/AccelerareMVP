"""
Amazon SES refuses unverified addresses while it is in its sandbox. A refused
email must never turn a saved account into a 500 page.
"""

from smtplib import SMTPException
from unittest import mock

import pytest
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import Account

from .test_signup_login import signup_data
from .test_verification import PASSWORD

REFUSED = mock.patch("django.core.mail.EmailMessage.send", side_effect=SMTPException("sandbox"))


@pytest.fixture(autouse=True)
def _fresh_cache(db):
    from django.core.cache import cache

    cache.clear()


@pytest.mark.django_db
def test_signup_keeps_the_account_when_the_mail_is_refused(client):
    with REFUSED:
        response = client.post(reverse("account_signup"), signup_data(), follow=True)
    assert Account.objects.filter(email="bob@example.com").exists()
    assert response.redirect_chain[-1][0] == reverse("account_email_verification_sent")
    assert "could not send the email" in response.content.decode()


@pytest.mark.django_db
def test_login_of_an_unverified_account_survives_a_refused_mail(client):
    services.register("bob@example.com", "+919876543210", None, PASSWORD)
    with REFUSED:
        response = client.post(
            "/accounts/login/", {"login": "bob@example.com", "password": PASSWORD}, follow=True
        )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert "could not send the email" in response.content.decode()


@pytest.mark.django_db
def test_login_resends_a_link_but_only_once_a_minute(client, mailoutbox):
    services.register("bob@example.com", "+919876543210", None, PASSWORD)
    for _ in range(2):
        client.post("/accounts/login/", {"login": "bob@example.com", "password": PASSWORD})
    assert len(mailoutbox) == 1


def test_the_login_resend_cooldown_matches_the_profile_page():
    from django.conf import settings

    assert (
        settings.ACCOUNT_RATE_LIMITS["confirm_email"]
        == f"1/{services.RESEND_COOLDOWN_SECONDS}s/key"
    )
