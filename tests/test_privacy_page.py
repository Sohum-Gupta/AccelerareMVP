"""
Milestone 7, PR 2: the privacy page.

/privacy/ says in plain words what the site keeps, who can see it and how to
have it deleted, and every page links to it from its foot. The founder chose
on 2026-11-13 to publish it from the facts, before a lawyer has read it, so
the tests here hold the sentences that can be checked to what the code does.
"""

import pytest
from django.urls import reverse

from apps.accounts import erasure
from apps.responses.organization_views import EXPORT_COLUMNS

from .test_erasure import complete
from .test_profile import verified_account
from .test_verification import PASSWORD

PRIVACY = "/privacy/"


def page(client):
    answer = client.get(PRIVACY)
    assert answer.status_code == 200
    return answer.content.decode().split("<main")[1].split("</main>")[0]


@pytest.mark.django_db
class TestThePage:
    def test_anyone_can_read_it_logged_in_or_not(self, client):
        assert "<h1>Privacy</h1>" in page(client)
        client.force_login(verified_account("bob@example.com"))
        assert "<h1>Privacy</h1>" in page(client)

    def test_it_is_at_the_address_its_name_gives(self):
        assert reverse("privacy") == PRIVACY

    def test_every_page_links_to_it_from_its_foot(self, client):
        for address in (reverse("account_login"), reverse("account_signup"), PRIVACY):
            foot = client.get(address).content.decode().split("<footer")[1]
            assert f'<a href="{PRIVACY}">Privacy</a>' in foot, address
        client.force_login(verified_account("bob@example.com"))
        for address in (reverse("responses:history"), reverse("account_profile")):
            foot = client.get(address).content.decode().split("<footer")[1]
            assert f'<a href="{PRIVACY}">Privacy</a>' in foot, address

    def test_it_says_the_same_to_everyone(self, client):
        """Nothing on it is about the reader, so it can be cached or printed."""
        logged_out = page(client)
        client.force_login(verified_account("bob@example.com"))
        assert page(client) == logged_out and "bob" not in logged_out


@pytest.mark.django_db
class TestHowToAsk:
    def test_with_no_inbox_chosen_it_prints_no_address(self, client, settings):
        settings.CONTACT_EMAIL = ""
        text = page(client)
        assert "@" not in text and "mailto:" not in text and "noreply" not in text
        assert "Ask the person at Accelerare who gave you access" in text
        assert "from the email address you log in with" in text

    def test_once_an_inbox_is_set_it_prints_that_address(self, client, settings):
        settings.CONTACT_EMAIL = "help@example.com"
        text = page(client)
        assert '<a href="mailto:help@example.com">help@example.com</a>' in text
        assert "Ask the person at Accelerare" not in text
        assert "from the email address you log in with" in text

    def test_the_setting_is_empty_unless_the_server_is_given_one(self, settings):
        assert settings.CONTACT_EMAIL == ""


@pytest.mark.django_db
class TestWhatItSaysIsTrue:
    def test_the_only_cookies_are_the_three_it_names(self, client):
        """Log in the real way, look around, and read the cookie jar."""
        verified_account("bob@example.com")
        client.get(reverse("account_login"))
        client.post(reverse("account_login"), {"login": "bob@example.com", "password": PASSWORD})
        for address in (reverse("responses:history"), reverse("account_profile"), PRIVACY):
            assert client.get(address).status_code == 200
        assert "sessionid" in client.cookies
        assert set(client.cookies) <= {"sessionid", "csrftoken", "messages"}
        assert (
            "one that keeps you logged in, one that keeps forms safe, and one that carries"
            in page(client)
        )

    def test_what_an_organizations_admins_see_is_what_their_file_holds(self, client):
        """The file is the most an admin can take away; the page must admit to all of it."""
        assert EXPORT_COLUMNS == (
            "name",
            "email",
            "started",
            "submitted",
            "results_level",
            "possible_repeat",
        )
        text = page(client)
        for words in (
            "your name",
            "the email address it knows you by",
            "the dates",
            "its results level",
            "a mark if it looks as though you have taken the survey before",
        ):
            assert words in text, words

    def test_an_erasure_does_what_the_page_says(self, client):
        text = page(client)
        assert "If you never finished a survey, everything about you is deleted." in text
        nothing = verified_account("nothing@example.com")
        assert erasure.erase_account(nothing).action == erasure.DELETE

        assert "keep the survey with nothing that links it to you" in text
        finished = verified_account("finished@example.com")
        complete(finished)
        assert erasure.erase_account(finished).action == erasure.ANONYMISE
        finished.refresh_from_db()
        assert finished.full_name == "" and "finished" not in finished.email
        assert not finished.contact_points.exists() and finished.responses.count() == 1

    def test_it_names_how_long_backups_last_as_the_procedure_does(self, client, settings):
        procedure = (settings.BASE_DIR / "docs" / "08-deletion-requests.md").read_text()
        assert "30 days" in procedure and "gone within 30 days" in page(client)

    def test_it_makes_no_claim_of_a_legal_review_and_no_promise_about_later(self, client):
        text = page(client).lower()
        for words in ("lawyer", "compliant", "gdpr", "ccpa", "we will never", "guarantee"):
            assert words not in text, words
