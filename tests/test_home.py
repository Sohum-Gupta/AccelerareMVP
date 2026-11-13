"""
The site's front door, "/". There is no landing page yet: it sends a logged-in
person to their profile and anyone else to the login page. The header's
"Accelerare" link and logging out both lead there, and used to show "Not Found".
"""

import pytest
from django.urls import reverse

from .test_profile import verified_account

LOGIN = "/accounts/login/"
PROFILE = "/accounts/profile/"


def test_the_front_door_has_the_shortest_address():
    assert reverse("home") == "/"


@pytest.mark.django_db
def test_someone_logged_out_is_sent_to_log_in(client):
    answer = client.get("/")
    assert answer.status_code == 302 and answer.url == LOGIN


@pytest.mark.django_db
def test_someone_logged_in_is_sent_to_their_profile(client):
    client.force_login(verified_account())
    answer = client.get("/")
    assert answer.status_code == 302 and answer.url == PROFILE


@pytest.mark.django_db
def test_logging_out_ends_on_the_login_page_not_on_not_found(client):
    client.force_login(verified_account())
    page = client.post("/accounts/logout/", follow=True)
    assert page.status_code == 200
    assert [address for address, _status in page.redirect_chain] == ["/", LOGIN]
    assert "Log in" in page.content.decode()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_the_header_link_leads_there_from_every_kind_of_page(client):
    assert '<a href="/" class="text-lg' in client.get(LOGIN).content.decode()
    client.force_login(verified_account())
    page = client.get(PROFILE)
    assert '<a href="/" class="text-lg' in page.content.decode()
    assert client.get("/", follow=True).redirect_chain[-1][0] == PROFILE


@pytest.mark.django_db
def test_the_answer_is_never_cached(client):
    """Or a browser could keep sending someone who has since logged in to the login page."""
    assert "no-cache" in client.get("/").headers["Cache-Control"]


@pytest.mark.django_db
def test_an_address_that_does_not_exist_is_still_not_found(client):
    assert client.get("/no-such-page/").status_code == 404
