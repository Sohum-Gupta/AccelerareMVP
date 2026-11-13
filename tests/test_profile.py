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


def test_login_lands_on_my_surveys(client, db):
    """The founder's choice of 2026-11-13: the page that says what to do next, not the settings."""
    account = verified_account()
    services.set_full_name(account, "Bob Builder")
    response, logged_in = login(client, "bob@example.com")
    assert logged_in
    assert response["Location"] == "/survey/history/"


def test_login_of_an_account_with_no_name_yet_lands_on_the_account_page(client, db):
    """It has something to put right first, and that page is where it is done."""
    verified_account()
    response, logged_in = login(client, "bob@example.com")
    assert logged_in
    assert response["Location"] == PROFILE
    assert "Please add yours." in client.get(PROFILE).content.decode()


def test_login_of_an_account_with_no_verified_email_lands_on_the_account_page(client, db):
    """Only an account made outside sign-up can be in this state (createsuperuser)."""
    Account.objects.create_superuser("root@example.com", PASSWORD, full_name="Root")
    response = client.post("/accounts/login/", {"login": "root@example.com", "password": PASSWORD})
    if "_auth_user_id" in client.session:  # allauth lets it in: it must land where it can verify
        assert response["Location"] == PROFILE


def test_someone_on_their_way_to_join_still_goes_there_after_login(client, db):
    from apps.accounts import arrival

    account = verified_account()
    services.set_full_name(account, "Bob Builder")
    client.get("/accounts/login/")  # start a session
    session = client.session
    session[arrival.SESSION_KEY] = {"channel": "code", "next": "/join/code/"}
    session.save()
    response = client.post("/accounts/login/", {"login": "bob@example.com", "password": PASSWORD})
    assert response["Location"] == "/join/code/"


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
    with mock.patch("django.core.mail.EmailMessage.send", side_effect=SMTPException("sandbox")):
        response = client.post("/accounts/profile/email/add/", {"email": "work@example.com"})
    assert response["Location"] == PROFILE
    assert signed_in.contact_points.filter(value_normalised="work@example.com").exists()
    page = client.get(PROFILE).content.decode()
    assert "could not send the email" in page and "Use Resend" in page


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
    assert "Add a phone" in client.get(PROFILE).content.decode()
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


# --- the page itself: a tidy settings page (T-19 point 3, 2026-11-13) ----------------
# Each card shows what is on the account; a form opens only when asked for.


def card(html, name):
    """The HTML of one card of the account page."""
    start = html.index(f'data-card="{name}"')
    return html[start : html.index("</section>", start)]


def test_each_card_shows_the_current_value_with_its_form_closed(client, signed_in):
    services.set_full_name(signed_in, "Bob Builder")
    second_email(signed_in, "work@example.com")
    html = client.get(PROFILE).content.decode()
    assert "<h1>Your account</h1>" in html
    name, emails, phone = card(html, "name"), card(html, "emails"), card(html, "phone")
    assert "Bob Builder" in name and "Change name" in name
    assert "bob@example.com" in emails and "Add an email" in emails
    assert "+91 98765 43210" in phone and "Change phone" in phone
    for one in (name, emails, phone):
        assert "<details>" in one and "<details open>" not in one
    # The form is still in the page, inside the closed part, so it works without JavaScript.
    assert 'action="/accounts/profile/name/"' in name
    assert 'action="/accounts/profile/phone/"' in phone


def test_the_phone_number_is_said_once(client, signed_in):
    assert "Current number" not in client.get(PROFILE).content.decode()


def test_the_survey_and_organization_boxes_are_gone_and_the_header_has_both(client, signed_in):
    html = client.get(PROFILE).content.decode()
    assert "Your surveys: start, continue" not in html and "Your organizations" not in html
    assert html.count('href="/survey/history/"') == 1
    assert html.count('href="/organizations/"') == 1


def test_a_missing_name_or_phone_has_its_form_open(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    html = client.get(PROFILE).content.decode()
    assert "<details open>" in card(html, "name") and "Add your name" in card(html, "name")
    assert "<details open>" in card(html, "phone") and "Add a phone" in card(html, "phone")


def test_a_form_that_comes_back_with_an_error_is_open_and_the_others_stay_closed(client, signed_in):
    services.set_full_name(signed_in, "Bob Builder")
    second_email(signed_in, "work@example.com")
    html = client.post(
        "/accounts/profile/phone/", {"phone": "12", "country": "IN"}
    ).content.decode()
    assert "<details open>" in card(html, "phone") and "Enter a valid phone number." in html
    assert "<details open>" not in card(html, "name")
    assert "<details open>" not in card(html, "emails")
    html = client.post("/accounts/profile/name/", {"full_name": ""}).content.decode()
    assert "<details open>" in card(html, "name") and "<details open>" not in card(html, "phone")
    html = client.post("/accounts/profile/email/add/", {"email": "nope"}).content.decode()
    assert "<details open>" in card(html, "emails")


def test_while_the_banner_shows_it_holds_the_only_add_email_form(client, signed_in):
    html = client.get(PROFILE).content.decode()
    assert "Add a personal email" in html and html.count('name="email"') == 1
    assert "Add an email" not in card(html, "emails")


def test_only_resend_is_a_main_button_among_an_emails_actions(client, signed_in):
    second_email(signed_in, "work@example.com")
    second_email(signed_in, "new@example.com", verified=False)
    emails = card(client.get(PROFILE).content.decode(), "emails")
    assert '<button type="submit">Resend link</button>' in emails
    assert '<button type="submit" class="button-secondary">Make login address</button>' in emails
    assert '<button type="submit" class="button-secondary">Remove</button>' in emails


def test_the_phone_forms_country_starts_as_the_country_of_the_saved_number(client, signed_in):
    """
    Found in a browser on 2026-11-13: for a number outside the US the hidden
    country stayed on the default while the flag showed the right one, so the
    same number retyped without its code was refused as not valid.
    """
    phone = card(client.get(PROFILE).content.decode(), "phone")  # an Indian number
    assert '<option value="IN" selected>' in phone
    services.change_phone(signed_in, "+44 7400 123456", None)
    assert '<option value="GB" selected>' in card(client.get(PROFILE).content.decode(), "phone")
    # Retyped the local way, with that country, it is accepted.
    client.post("/accounts/profile/phone/", {"phone": "07400 123457", "country": "GB"})
    assert signed_in.contact_points.get(kind="phone").value_normalised == "+447400123457"


def test_the_page_script_reads_the_pickers_country_as_it_starts():
    from pathlib import Path

    from django.conf import settings

    script = (Path(settings.BASE_DIR) / "static" / "js" / "phone-input.js").read_text()
    assert (
        "getSelectedCountryData()" in script
        and "select.value = chosen.iso2.toUpperCase()" in script
    )
