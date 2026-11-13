"""
Milestone 3, PR 1: the account's full name. Sign-up asks for it, the profile
page shows and changes it (and asks accounts made earlier for it), the staff
admin shows and searches it, and erasing an account removes it.
"""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts import erasure, services
from apps.accounts.models import Account
from apps.accounts.normalisers import FULL_NAME_MAX_LENGTH, clean_full_name
from apps.entitlements import services as licences
from apps.responses.models import Response
from apps.survey.services import current_version

from .test_profile import verified_account
from .test_signup_login import SIGNUP, signup_data
from .test_verification import PASSWORD

PROFILE = "/accounts/profile/"
NAME = "/accounts/profile/name/"


# --- the rule ------------------------------------------------------------------


def test_a_name_is_trimmed_and_its_spaces_collapsed_but_otherwise_kept():
    assert clean_full_name("  bob   van  EXAMPLE \n") == "bob van EXAMPLE"


@pytest.mark.parametrize(
    "bad", ["", "   ", None, "x" * (FULL_NAME_MAX_LENGTH + 1), "Bob\x00Example"]
)
def test_an_empty_too_long_or_unstorable_name_is_refused(bad):
    with pytest.raises(ValidationError):
        clean_full_name(bad)


def test_the_form_and_the_column_allow_the_same_length():
    assert Account._meta.get_field("full_name").max_length == FULL_NAME_MAX_LENGTH


# --- sign-up -------------------------------------------------------------------


@pytest.mark.django_db
def test_signup_stores_the_name(client):
    response = client.post(SIGNUP, signup_data(full_name="  Bob   Example "))
    assert response.status_code == 302
    assert Account.objects.get(email="bob@example.com").full_name == "Bob Example"


@pytest.mark.django_db
@pytest.mark.parametrize("blank", ["", "   "])
def test_signup_without_a_name_is_refused_and_creates_nothing(client, blank):
    response = client.post(SIGNUP, signup_data(full_name=blank))
    assert response.status_code == 200
    assert "Enter your name." in response.content.decode()
    assert not Account.objects.exists()


@pytest.mark.django_db
def test_the_signup_page_asks_for_the_name_first(client):
    html = client.get(SIGNUP).content.decode()
    assert 'name="full_name"' in html
    assert html.index('name="full_name"') < html.index('name="email"')


@pytest.mark.django_db
def test_register_without_a_name_still_works_for_other_callers():
    # createsuperuser and older code paths have no name to give.
    account = services.register("bob@example.com", "+919876543210", None, PASSWORD)
    assert account.full_name == ""
    assert Account.objects.create_superuser("root@example.com", PASSWORD).full_name == ""


# --- the profile page ----------------------------------------------------------


@pytest.fixture
def signed_in(client, db):
    account = verified_account()
    client.force_login(account)
    return account


def test_an_account_without_a_name_is_asked_for_it(client, signed_in):
    html = client.get(PROFILE).content.decode()
    assert "Add your name" in html
    assert f'action="{NAME}"' in html


def test_saving_a_name_stores_it_and_the_prompt_goes(client, signed_in):
    response = client.post(NAME, {"full_name": " Bob  Example "}, follow=True)
    signed_in.refresh_from_db()
    assert signed_in.full_name == "Bob Example"
    html = response.content.decode()
    assert "Name saved." in html
    assert "Add your name" not in html
    assert 'value="Bob Example"' in html


def test_a_name_can_be_changed_but_not_emptied(client, signed_in):
    services.set_full_name(signed_in, "Bob Example")
    client.post(NAME, {"full_name": "Robert Example"})
    signed_in.refresh_from_db()
    assert signed_in.full_name == "Robert Example"

    response = client.post(NAME, {"full_name": "  "})
    assert response.status_code == 200
    assert "Enter your name." in response.content.decode()
    signed_in.refresh_from_db()
    assert signed_in.full_name == "Robert Example"


def test_an_over_long_name_is_refused(client, signed_in):
    response = client.post(NAME, {"full_name": "x" * (FULL_NAME_MAX_LENGTH + 1)})
    assert response.status_code == 200
    signed_in.refresh_from_db()
    assert signed_in.full_name == ""


def test_changing_the_name_needs_a_login_and_a_post(client, db):
    response = client.post(NAME, {"full_name": "Bob Example"})
    assert response.status_code == 302 and response["Location"].startswith("/accounts/login/")
    client.force_login(verified_account())
    assert client.get(NAME).status_code == 405


def test_a_name_with_markup_is_shown_as_text(client, signed_in):
    services.set_full_name(signed_in, "<b>Bob</b>")
    html = client.get(PROFILE).content.decode()
    assert "<b>Bob</b>" not in html
    assert "&lt;b&gt;Bob&lt;/b&gt;" in html


# --- the staff admin -----------------------------------------------------------


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


def test_the_admin_lists_and_searches_by_name(client, root):
    bob = verified_account("bob@example.com")
    services.set_full_name(bob, "Bob Example")
    verified_account("carol@example.com")

    listing = client.get("/admin/accounts/account/").content.decode()
    assert "Bob Example" in listing

    found = client.get("/admin/accounts/account/?q=Bob+Exam").content.decode()
    assert "bob@example.com" in found
    assert "carol@example.com" not in found


def test_the_admin_account_page_shows_the_name(client, root):
    bob = verified_account("bob@example.com")
    services.set_full_name(bob, "Bob Example")
    html = client.get(f"/admin/accounts/account/{bob.pk}/change/").content.decode()
    assert 'name="full_name"' in html and "Bob Example" in html


# --- erasure -------------------------------------------------------------------


@pytest.mark.django_db
def test_erasing_an_account_with_a_completed_survey_removes_its_name():
    bob = verified_account("bob@example.com")
    services.set_full_name(bob, "Bob Example")
    Response.objects.create(
        account=bob,
        survey_version=current_version(),
        entitlement=licences.grant_individual(bob.person, 2, "manual", None),
        status="submitted",
        submitted_at=timezone.now(),
    )

    assert erasure.erase_account(bob).action == erasure.ANONYMISE

    bob.refresh_from_db()
    assert bob.full_name == ""
    assert bob.anonymised_at is not None


def test_the_name_of_an_erased_account_cannot_be_typed_back_in_the_admin(client, root):
    bob = verified_account("bob@example.com")
    Response.objects.create(
        account=bob,
        survey_version=current_version(),
        entitlement=licences.grant_individual(bob.person, 2, "manual", None),
        status="submitted",
        submitted_at=timezone.now(),
    )
    erasure.erase_account(bob)
    html = client.get(f"/admin/accounts/account/{bob.pk}/change/").content.decode()
    assert 'name="full_name"' not in html
