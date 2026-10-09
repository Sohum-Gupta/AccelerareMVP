"""
The pages a person sees: the shared layout, signup and login. The rules behind
them (what is a valid phone, who owns an address) are tested with the services.
"""

import re

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts import services
from apps.accounts.forms import country_choices
from apps.accounts.models import Account, ContactPoint, Person

from .test_verification import PASSWORD, last_link, login

SIGNUP = "/accounts/signup/"


def signup_data(**overrides):
    data = {
        "email": "Bob@Example.com",
        "phone": "098765 43210",
        "country": "IN",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    return {**data, **overrides}


def strip_token(content: bytes) -> str:
    return re.sub(
        r'(csrfmiddlewaretoken" value=|X-CSRFToken": )"[^"]*"', r"\1TOKEN", content.decode()
    )


# --- layout ------------------------------------------------------------------


def test_layout_loads_css_and_htmx_and_links_signed_out_visitors_to_login(client, db):
    html = client.get(SIGNUP).content.decode()
    assert "css/app.css" in html
    assert "js/htmx.min.js" in html
    assert 'href="/accounts/login/"' in html


@pytest.mark.django_db
def test_signed_in_nav_shows_the_email_and_a_post_logout_form(client):
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    client.force_login(account)
    html = client.get("/accounts/password/reset/").content.decode()
    assert "bob@example.com" in html
    assert 'action="/accounts/logout/"' in html


def test_flash_messages_are_rendered_once_by_the_shared_layout():
    from django.contrib.messages.storage.base import Message
    from django.template.loader import render_to_string

    messages = [Message(25, "Welcome aboard")]
    for template in ("base.html", "allauth/layouts/base.html", "account/verification_sent.html"):
        html = render_to_string(template, {"messages": messages})
        assert html.count("Welcome aboard") == 1, template


# --- country list --------------------------------------------------------------


def test_countries_start_with_us_india_uk_then_the_alphabetical_rest():
    choices = country_choices()
    assert [code for code, _ in choices[:3]] == ["US", "IN", "GB"]
    rest = [name for _, name in choices[3:]]
    assert rest == sorted(rest)
    assert len(choices) > 200


# --- signup --------------------------------------------------------------------


@pytest.mark.django_db
def test_signup_creates_the_account_sends_the_link_and_redirects(client):
    response = client.post(SIGNUP, signup_data())

    assert response.status_code == 302
    assert response.url == "/accounts/confirm-email/"
    account = Account.objects.get(email="bob@example.com")
    assert Person.objects.count() == 1
    assert account.contact_points.count() == 2
    assert (
        account.contact_points.get(kind=ContactPoint.Kind.PHONE).value_normalised == "+919876543210"
    )
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["bob@example.com"]
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_signup_for_an_existing_email_looks_identical_and_sends_nothing(client):
    fresh = client.post(SIGNUP, signup_data(email="new@example.com"), follow=True)
    services.register("bob@example.com", "+919876543210", None, PASSWORD)
    mail.outbox.clear()

    repeat = client.post(SIGNUP, signup_data(email="BOB@example.com"), follow=True)

    assert repeat.redirect_chain == [("/accounts/confirm-email/", 302)]
    assert repeat.redirect_chain == fresh.redirect_chain
    # Every response carries its own CSRF token; nothing else may differ.
    assert strip_token(repeat.content) == strip_token(fresh.content)
    assert b"exist" not in repeat.content.lower()
    assert mail.outbox == []
    assert Account.objects.filter(email__iexact="bob@example.com").count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"phone": "123"}, "phone"),
        ({"password1": "short", "password2": "short"}, "password"),
        ({"password2": "something-else-entirely"}, "do not match"),
        ({"email": "not-an-email"}, "email"),
        ({"country": "ZZ"}, "choice"),
    ],
)
def test_signup_shows_errors_and_creates_nothing(client, overrides, message):
    response = client.post(SIGNUP, signup_data(**overrides))

    assert response.status_code == 200
    assert message in response.content.decode().lower()
    assert not Account.objects.filter(email="bob@example.com").exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_signup_page_lists_us_first_and_redirects_signed_in_people(client):
    html = client.get(SIGNUP).content.decode()
    assert html.index("United States") < html.index("India") < html.index("United Kingdom")
    assert html.index("United Kingdom") < html.index("Afghanistan")

    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    client.force_login(account)
    assert client.get(SIGNUP).status_code == 302


@pytest.mark.django_db
def test_signup_then_verify_then_login(client):
    client.post(SIGNUP, signup_data())
    client.post(last_link())

    response, logged_in = login(client, "bob@example.com")

    assert logged_in
    assert response.status_code == 302


# --- login ---------------------------------------------------------------------


@pytest.mark.django_db
def test_login_page_uses_allauths_field_names(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'name="login"' in html
    assert 'name="password"' in html
    assert 'href="/accounts/signup/"' in html


@pytest.mark.django_db
def test_unverified_login_goes_to_check_your_inbox_and_sends_a_fresh_link(client):
    services.register("bob@example.com", "+919876543210", None, PASSWORD)

    response, logged_in = login(client, "bob@example.com")

    assert not logged_in
    assert response.status_code == 302
    assert response.url == "/accounts/confirm-email/"
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_wrong_password_shows_an_error_on_the_login_page(client):
    services.register("bob@example.com", "+919876543210", None, PASSWORD)

    response = client.post("/accounts/login/", {"login": "bob@example.com", "password": "wrong"})

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


# --- phone widget --------------------------------------------------------------


@pytest.mark.django_db
def test_signup_page_wires_up_the_phone_widget(client):
    html = client.get(reverse("account_signup")).content.decode()
    assert "data-phone-input" in html and "data-phone-root" in html
    assert "intlTelInput.min.js" in html and "js/phone-input.js" in html
    # Still a real dropdown in the HTML, so the form works without JavaScript.
    assert '<select name="country"' in html


def test_vendored_widget_files_exist_where_the_css_expects_them():
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "static/vendor/intl-tel-input"
    for name in ("js/intlTelInput.min.js", "css/intlTelInput.min.css", "img/flags.webp"):
        assert (base / name).is_file(), name
