"""
Milestone 7, PR 4: an error report says which account met the error, by
number only.

Sentry is given no personal data, so a report used to say nothing about who
met it. A few lines of middleware now attach the account's number, and nothing
else: never the email address or the name.
"""

import pytest
import sentry_sdk
from django.conf import settings

from apps.accounts import middleware

from .test_profile import verified_account


@pytest.fixture
def told(monkeypatch):
    """Everything Sentry is told about the user during the test, in order."""
    calls = []
    monkeypatch.setattr(sentry_sdk, "set_user", calls.append)
    return calls


@pytest.mark.django_db
class TestWhatSentryIsTold:
    def test_the_account_number_and_nothing_else(self, client, told):
        bob = verified_account("bob@example.com")
        client.force_login(bob)
        client.get("/privacy/")
        assert told == [{"id": bob.pk}]

    def test_never_the_email_address_or_the_name(self, client, told):
        bob = verified_account("bob@example.com")
        type(bob).objects.filter(pk=bob.pk).update(full_name="Bob Example")
        client.force_login(bob)
        client.get("/privacy/")
        assert "bob" not in str(told).lower() and "example" not in str(told).lower()
        assert set(told[0]) == {"id"}

    def test_a_logged_out_visitor_clears_it(self, client, told):
        """Otherwise the next report from this worker could carry the last person's number."""
        client.get("/privacy/")
        assert told == [None]

    def test_a_visitor_with_a_session_who_is_not_logged_in_has_no_number(self, client, told):
        session = client.session
        session["something"] = "kept between pages"
        session.save()
        client.get("/privacy/")
        assert told == [None]

    def test_it_is_told_on_every_request_even_one_that_is_not_found(self, client, told):
        bob = verified_account("bob@example.com")
        client.force_login(bob)
        client.get("/no/such/page/")
        client.get("/health")
        assert told == [{"id": bob.pk}, {"id": bob.pk}]

    def test_it_is_told_before_the_page_runs_so_a_fault_carries_it(self, client, told, settings):
        settings.ROOT_URLCONF = "tests.urls_with_a_fault"
        client.raise_request_exception = False
        bob = verified_account("bob@example.com")
        client.force_login(bob)
        assert client.get("/a-fault/").status_code == 500
        assert told == [{"id": bob.pk}]


@pytest.mark.django_db
def test_a_visitor_with_no_session_costs_no_database_query(client, django_assert_num_queries):
    """/health promises to touch nothing, and the uptime checker calls it every few minutes."""
    with django_assert_num_queries(0):
        assert client.get("/health").status_code == 200


def test_it_runs_straight_after_the_login_is_worked_out():
    order = settings.MIDDLEWARE
    ours = order.index("apps.accounts.middleware.SentryAccountMiddleware")
    assert order[ours - 1] == "django.contrib.auth.middleware.AuthenticationMiddleware"


def test_with_sentry_not_set_up_the_call_does_nothing(rf):
    """On a laptop and in tests there is no SENTRY_DSN; the real call must be harmless."""
    request = rf.get("/")
    answer = middleware.SentryAccountMiddleware(lambda request: "the page")(request)
    assert answer == "the page"


def test_production_still_sends_no_personal_data():
    """The settings this builds on (Milestone 2). If one is loosened, the number is no longer alone."""
    source = (settings.BASE_DIR / "config" / "settings" / "production.py").read_text()
    lines = {line.strip() for line in source.splitlines()}
    for line in (
        "send_default_pii=False,",
        'max_request_body_size="never",',
        "include_local_variables=False,",
    ):
        assert line in lines, line
