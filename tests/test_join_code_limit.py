"""
Milestone 7, PR 3: a join code cannot be found by trying many.

After ten codes that were refused within an hour, an account is asked to wait
until the hour is up, and nothing it types is looked at meanwhile. The count is
per account (a code is only checked for someone logged in), lives in the
site's cache and forgets itself.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.enterprises import services as orgs
from apps.enterprises import throttle
from apps.enterprises.models import Membership

from .test_join_pages import CODE, acme, carol, text_of  # noqa: F401
from .test_profile import verified_account

WRONG = "ABCDE-FGH23"
NOT_VALID = "That code is not valid. Check it and try again."


def guess(client, times, code=WRONG):
    page = ""
    for _ in range(times):
        page = text_of(client.post(CODE, {"code": code}))
    return page


def real_code(acme):
    return orgs.display_code(orgs.create_code(acme[1], 5).code)


@pytest.mark.django_db
class TestTenRefusalsAnHour:
    def test_the_first_ten_are_answered_as_before(self, client, acme, carol):
        assert NOT_VALID in guess(client, 10)

    def test_the_eleventh_is_asked_to_wait(self, client, acme, carol):
        guess(client, 10)
        page = guess(client, 1)
        assert throttle.MESSAGE in page and NOT_VALID not in page
        assert "wait an hour" in page

    def test_while_waiting_no_code_is_even_looked_at(self, client, acme, carol):
        """Not a wrong one and not a right one: the answer says nothing about the code."""
        code = real_code(acme)
        guess(client, 10)
        with CaptureQueriesContext(connection) as queries:
            page = guess(client, 1, code)
        assert throttle.MESSAGE in page and "Join Acme?" not in page
        assert not any("enterprises_joincode" in query["sql"] for query in queries)
        # Nor does pressing "confirm" get round it.
        client.post(CODE, {"code": code, "confirm": "yes"})
        assert not Membership.objects.filter(account=carol).exists()

    def test_a_working_code_within_the_ten_still_joins(self, client, acme, carol):
        code = real_code(acme)
        guess(client, 9)
        assert "Join Acme?" in guess(client, 1, code)
        client.post(CODE, {"code": code, "confirm": "yes"})
        assert Membership.objects.filter(account=carol, enterprise=acme[0]).exists()

    def test_a_working_code_does_not_use_up_a_try(self, client, acme, carol):
        code = real_code(acme)
        guess(client, 9)
        guess(client, 3, code)  # looked at three times, never refused
        assert NOT_VALID in guess(client, 1)  # the tenth refusal
        assert throttle.MESSAGE in guess(client, 1)

    def test_every_kind_of_refusal_counts(self, client, acme, carol):
        """A code that exists but is switched off tells a guesser as much as one that does not."""
        made = orgs.create_code(acme[1], 5)
        orgs.revoke_code(made, by=acme[1])
        switched_off = orgs.display_code(made.code)
        assert throttle.MESSAGE not in guess(client, 10, switched_off)
        assert throttle.MESSAGE in guess(client, 1, switched_off)

    def test_typing_the_code_of_an_organization_you_are_already_in_is_not_counted(
        self, client, acme, carol
    ):
        code = real_code(acme)
        orgs.redeem_code(code, carol)
        for _ in range(12):
            answer = client.post(CODE, {"code": code})
            assert answer.status_code == 302 and answer.url == "/organizations/acme/"
        assert not throttle.blocked(carol)

    def test_something_that_cannot_be_a_code_is_not_counted(self, client, acme, carol):
        """A typing slip the form itself turns away never reaches the codes."""
        guess(client, 15, "x")
        assert NOT_VALID in guess(client, 1)

    def test_opening_the_page_is_never_counted_or_refused(self, client, acme, carol):
        guess(client, 11)
        assert client.get(CODE).status_code == 200
        assert throttle.MESSAGE not in text_of(client.get(CODE))


@pytest.mark.django_db
class TestItIsPerAccountAndForgets:
    def test_another_account_is_not_affected(self, client, acme, carol):
        guess(client, 11)
        client.force_login(verified_account("dave@example.com"))
        assert NOT_VALID in guess(client, 1)
        assert "Join Acme?" in guess(client, 1, real_code(acme))

    def test_after_the_hour_it_works_again(self, client, acme, carol, monkeypatch):
        guess(client, 11)
        later = throttle._now() + throttle.WINDOW + 1
        monkeypatch.setattr(throttle, "_now", lambda: later)
        assert NOT_VALID in guess(client, 1)
        assert not throttle.blocked(carol)

    def test_the_hour_runs_from_the_first_refusal_not_the_last(
        self, client, acme, carol, monkeypatch
    ):
        start = throttle._now()
        guess(client, 5)
        monkeypatch.setattr(throttle, "_now", lambda: start + throttle.WINDOW - 60)
        guess(client, 5)
        assert throttle.blocked(carol)
        monkeypatch.setattr(throttle, "_now", lambda: start + throttle.WINDOW + 1)
        assert not throttle.blocked(carol)

    def test_a_logged_out_visitor_is_told_to_log_in_and_nothing_about_the_code(self, client, acme):
        """The code waits for the login; it is not checked, so there is nothing to count."""
        for _ in range(12):
            page = text_of(client.post(CODE, {"code": WRONG}))
            assert NOT_VALID not in page and throttle.MESSAGE not in page
            assert "/accounts/login/" in page

    def test_the_count_holds_a_number_and_a_time_and_nothing_about_the_code(
        self, client, acme, carol
    ):
        from django.core.cache import cache

        guess(client, 3)
        kept = cache.get(f"join-code-refused:{carol.pk}")
        assert set(kept) == {"count", "until"} and kept["count"] == 3


@pytest.mark.django_db
def test_an_invite_link_is_not_limited(client, acme, carol):
    """Its secret is far longer than a code and only works for the invited address."""
    for _ in range(12):
        assert client.get("/join/invite/not-a-real-token/").status_code in (200, 404)
    assert not throttle.blocked(carol)
