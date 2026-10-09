"""
Milestone 1, PR 6: the profile page. The rules live in services (tested in
test_account_services.py); these tests check the views wire them up, that one
account cannot touch another's contacts, and the "add a personal email" banner.
"""

from smtplib import SMTPException
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.core.cache import cache
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import Account, ContactPoint

from .test_verification import PASSWORD, login

PROFILE = "/accounts/profile/"


def verified_account(email="bob@example.com"):
    account = services.register(email, "+919876543210", None, PASSWORD)
    ContactPoint.objects.filter(account=account, kind="email").update(verified_at=timezone.now())
    EmailAddress.objects.filter(user=account).update(verified=True)
    return account


def second_email(account, email, verified=True):
    contact = services.add_email(account, email)
    if verified:
        ContactPoint.objects.filter(pk=contact.pk).update(verified_at=timezone.now())
        EmailAddress.objects.filter(user=account, email=email).update(verified=True)
    contact.refresh_from_db()
    return contact


@pytest.fixture
def signed_in(client, db):
    account = verified_account()
    client.force_login(account)
    return account


@pytest.fixture(autouse=True)
def _fresh_cache(db):
    cache.clear()


# --- access and landing ------------------------------------------------------


def test_profile_needs_login(client, db):
    response = client.get(PROFILE)
    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_login_lands_on_the_profile(client, db):
    verified_account()
    response, logged_in = login(client, "bob@example.com")
    assert logged_in
    assert response["Location"] == PROFILE


def test_signed_in_visitor_to_signup_goes_to_the_profile(client, signed_in):
    assert client.get("/accounts/signup/")["Location"] == PROFILE


def test_profile_lists_emails_and_phone(client, signed_in):
    second_email(signed_in, "work@example.com", verified=False)
    html = client.get(PROFILE).content.decode()
    assert "bob@example.com" in html
    assert "work@example.com" in html
    assert "+919876543210" in html
    assert "Not verified yet" in html


def test_every_action_is_post_only(client, signed_in):
    contact = signed_in.contact_points.filter(kind="email").first()
    for url in (
        "/accounts/profile/email/add/",
        f"/accounts/profile/email/{contact.pk}/resend/",
        f"/accounts/profile/email/{contact.pk}/primary/",
        f"/accounts/profile/contact/{contact.pk}/remove/",
        "/accounts/profile/phone/",
        "/accounts/profile/personal-email-prompt/dismiss/",
    ):
        assert client.get(url).status_code == 405, url


# --- add, resend, make primary, remove ---------------------------------------


def test_add_email_saves_it_unverified_and_sends_a_link(client, signed_in):
    response = client.post("/accounts/profile/email/add/", {"email": "Work@Example.com"})
    assert response["Location"] == PROFILE
    contact = signed_in.contact_points.get(value_normalised="work@example.com")
    assert contact.verified_at is None
    assert mail.outbox[-1].to == ["work@example.com"]


def test_add_email_rejects_a_duplicate_with_a_message(client, signed_in):
    response = client.post("/accounts/profile/email/add/", {"email": "bob@example.com"})
    assert response.status_code == 200
    assert "already on your account" in response.content.decode()


def test_add_email_keeps_the_address_when_the_mail_server_refuses(client, signed_in):
    with mock.patch.object(services, "send_verification", side_effect=SMTPException("sandbox")):
        response = client.post("/accounts/profile/email/add/", {"email": "work@example.com"})
    assert response["Location"] == PROFILE
    assert signed_in.contact_points.filter(value_normalised="work@example.com").exists()
    assert "could not send" in client.get(PROFILE).content.decode()


def test_resend_sends_once_then_waits_a_minute(client, signed_in):
    contact = second_email(signed_in, "work@example.com", verified=False)
    url = f"/accounts/profile/email/{contact.pk}/resend/"
    client.post(url)
    client.post(url)
    assert len(mail.outbox) == 1
    assert "a moment ago" in client.get(PROFILE).content.decode()


def test_resend_for_a_verified_email_sends_nothing(client, signed_in):
    contact = second_email(signed_in, "work@example.com")
    client.post(f"/accounts/profile/email/{contact.pk}/resend/")
    assert mail.outbox == []


def test_make_primary_changes_the_login_address(client, signed_in):
    contact = second_email(signed_in, "work@example.com")
    client.post(f"/accounts/profile/email/{contact.pk}/primary/")
    signed_in.refresh_from_db()
    assert signed_in.email == "work@example.com"


def test_make_primary_of_an_unverified_email_is_refused_with_a_message(client, signed_in):
    contact = second_email(signed_in, "work@example.com", verified=False)
    client.post(f"/accounts/profile/email/{contact.pk}/primary/")
    signed_in.refresh_from_db()
    assert signed_in.email == "bob@example.com"
    assert "Verify that email" in client.get(PROFILE).content.decode()


def test_remove_deletes_a_secondary_email_but_refuses_the_primary(client, signed_in):
    extra = second_email(signed_in, "work@example.com")
    primary = signed_in.contact_points.get(value_normalised="bob@example.com")
    client.post(f"/accounts/profile/contact/{primary.pk}/remove/")
    assert ContactPoint.objects.filter(pk=primary.pk).exists()
    client.post(f"/accounts/profile/contact/{extra.pk}/remove/")
    assert not ContactPoint.objects.filter(pk=extra.pk).exists()


def test_another_accounts_contact_is_a_404_and_untouched(client, signed_in):
    other = verified_account("eve@example.com")
    theirs = second_email(other, "eve2@example.com")
    for action in ("email/%d/resend/", "email/%d/primary/", "contact/%d/remove/"):
        response = client.post("/accounts/profile/" + action % theirs.pk)
        assert response.status_code == 404
    assert ContactPoint.objects.filter(pk=theirs.pk).exists()


# --- phone -------------------------------------------------------------------


def test_change_phone_saves_the_new_number_unverified(client, signed_in):
    response = client.post("/accounts/profile/phone/", {"phone": "415 555 2671", "country": "US"})
    assert response["Location"] == PROFILE
    phone = signed_in.contact_points.get(kind="phone")
    assert phone.value_normalised == "+14155552671"
    assert phone.verified_at is None


def test_bad_phone_shows_an_error_and_changes_nothing(client, signed_in):
    response = client.post("/accounts/profile/phone/", {"phone": "123", "country": "US"})
    assert response.status_code == 200
    assert signed_in.contact_points.get(kind="phone").value_normalised == "+919876543210"


def test_an_account_without_a_phone_can_add_one(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    assert "Add phone" in client.get(PROFILE).content.decode()
    client.post("/accounts/profile/phone/", {"phone": "+44 7911 123456", "country": "GB"})
    assert account.contact_points.get(kind="phone").value_normalised == "+447911123456"


def test_profile_has_the_phone_widget(client, signed_in):
    html = client.get(PROFILE).content.decode()
    assert "data-phone-input" in html
    assert "phone-input.js" in html


# --- the personal-email banner -----------------------------------------------


def test_banner_shows_with_one_email_and_stops_after_not_now(client, signed_in):
    assert "Add a personal email" in client.get(PROFILE).content.decode()
    client.post("/accounts/profile/personal-email-prompt/dismiss/")
    signed_in.refresh_from_db()
    assert signed_in.personal_email_prompt_dismissed_at is not None
    assert "Add a personal email" not in client.get(PROFILE).content.decode()


def test_adding_an_email_stays_possible_after_dismissing_the_banner(client, signed_in):
    client.post("/accounts/profile/personal-email-prompt/dismiss/")
    html = client.get(PROFILE).content.decode()
    assert 'action="/accounts/profile/email/add/"' in html
    client.post("/accounts/profile/email/add/", {"email": "me@example.org"})
    assert signed_in.contact_points.filter(value_normalised="me@example.org").exists()


def test_banner_is_gone_once_there_is_a_second_email(client, signed_in):
    second_email(signed_in, "work@example.com", verified=False)
    assert "Add a personal email" not in client.get(PROFILE).content.decode()
    assert 'action="/accounts/profile/email/add/"' in client.get(PROFILE).content.decode()
