"""
Milestone 3, PR 11: the admin's responses pages.

/organizations/<slug>/responses/ lists the surveys taken for the organization
with filters and a choice of order; /organizations/<slug>/responses/<id>/ shows
one. An admin sees who took it, its status, its dates, its results level and
the possible-repeat mark.

That an admin sees only their own organization's surveys, never one taken
personally, and never an answer, the self-report or the progress, is in
tests/test_tenant_isolation.py (TestTheResponsesPages).
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.responses import services as surveys
from apps.responses.models import Response

from .orgs import new_member
from .test_profile import verified_account
from .test_response_context import acme, finish, grant  # noqa: F401

ACME = "/organizations/acme/"
TABLE = "/organizations/acme/responses/"


@pytest.fixture
def admin(client, acme):
    """Acme's admin, logged in. Returns the admin's membership."""
    client.force_login(acme[1].account)
    return acme[1]


def member(acme, name, tier=2):
    """A named member of Acme with a licence. Returns the membership."""
    first = name.split()[0].lower()
    membership = new_member(acme[0], f"{first}@example.com")
    accounts.set_full_name(membership.account, name)
    grant(membership, tier)
    return membership


def started(membership, days_ago=0):
    """The member's attempt for Acme, started some days ago."""
    response = surveys.start_response(membership.account, membership)
    when = timezone.now() - timedelta(days=days_ago)
    Response.objects.filter(pk=response.pk).update(started_at=when)
    return response


def submitted(membership, days_ago=0, started_days_ago=None):
    """The member's finished attempt for Acme, submitted some days ago."""
    response = finish(
        started(membership, days_ago if started_days_ago is None else started_days_ago)
    )
    when = timezone.now() - timedelta(days=days_ago)
    Response.objects.filter(pk=response.pk).update(submitted_at=when)
    return response


def page(client, query=""):
    answer = client.get(TABLE + query)
    assert answer.status_code == 200, answer.status_code
    return answer


def names(client, query=""):
    return [row["name"] for row in page(client, query).context["rows"]]


def text(client, address):
    answer = client.get(address)
    assert answer.status_code == 200, f"{address} answered {answer.status_code}"
    return answer.content.decode().split("<main")[1]


@pytest.fixture
def three(acme):
    """Carol submitted (tier 1), Bob in progress (tier 2), Alice submitted (tier 3)."""
    return {
        "carol": submitted(member(acme, "Carol Example", 1), days_ago=1, started_days_ago=5),
        "bob": started(member(acme, "Bob Example", 2), days_ago=3),
        "alice": submitted(member(acme, "Alice Example", 3), days_ago=2, started_days_ago=4),
    }


@pytest.mark.django_db
class TestTheTable:
    def test_with_no_surveys_it_says_so_and_offers_no_filters(self, client, admin):
        body = text(client, TABLE)
        assert "Nobody has started the survey for Acme yet." in body
        assert "<select" not in body

    def test_each_row_says_who_when_its_status_and_its_level(self, client, acme, admin, three):
        body = text(client, TABLE)

        def day(ago):
            return f"{timezone.localtime(timezone.now() - timedelta(days=ago)):%-d %B %Y}"

        carol = body.split(f'data-response="{three["carol"].pk}"')[1].split("</li>")[0]
        assert "Carol Example" in carol and "carol@example.com" in carol
        assert f"Submitted on {day(1)}" in carol and f"Started {day(5)}" in carol
        assert "Tier 1" in carol and "Possible repeat" not in carol
        bob = body.split(f'data-response="{three["bob"].pk}"')[1].split("</li>")[0]
        assert "In progress" in bob and "Submitted on" not in bob and "Tier 2" in bob
        assert f"{ACME}responses/{three['bob'].pk}/" in bob
        assert "3 responses" in body

    def test_the_newest_start_comes_first_unless_another_order_is_chosen(
        self, client, admin, three
    ):
        assert names(client) == ["Bob Example", "Alice Example", "Carol Example"]
        assert names(client, "?sort=-started") == names(client)
        assert names(client, "?sort=started") == ["Carol Example", "Alice Example", "Bob Example"]
        # By submit date, the unfinished one last.
        assert names(client, "?sort=-submitted") == [
            "Carol Example",
            "Alice Example",
            "Bob Example",
        ]
        assert names(client, "?sort=member") == ["Alice Example", "Bob Example", "Carol Example"]

    def test_by_name_people_without_one_and_erased_members_come_last(self, client, acme, admin):
        from apps.accounts import erasure

        submitted(member(acme, "Bob Example"))
        nameless = new_member(acme[0], "nameless@example.com")
        grant(nameless)
        started(nameless)
        erased = member(acme, "Zed Example")
        submitted(erased)
        erasure.erase_account(erased.account)
        submitted(member(acme, "alice example"))
        assert names(client, "?sort=member") == [
            "alice example",
            "Bob Example",
            "",
            "Erased member",
        ]
        assert "No name yet" in text(client, TABLE)

    def test_filters_by_status_level_and_possible_repeat(self, client, admin, three):
        assert set(names(client, "?status=submitted")) == {"Carol Example", "Alice Example"}
        assert names(client, "?status=draft") == ["Bob Example"]
        assert names(client, "?tier=3") == ["Alice Example"]
        assert names(client, "?status=submitted&tier=2") == []
        assert names(client, "?repeat=yes") == []
        Response.objects.filter(pk=three["carol"].pk).update(possible_repeat=True)
        assert names(client, "?repeat=yes") == ["Carol Example"]
        assert "Possible repeat</strong>" in text(client, TABLE + "?repeat=yes")

    def test_a_filtered_table_says_how_many_of_how_many(self, client, admin, three):
        body = text(client, TABLE + "?status=draft")
        assert "Showing 1 of 3 responses" in body and "Clear filters" in body
        assert 'value="draft" selected' in body
        assert "No response matches these filters." in text(
            client, TABLE + "?status=submitted&tier=2"
        )
        assert "Clear filters" not in text(client, TABLE + "?sort=member")

    @pytest.mark.parametrize(
        "query", ["?status=finished", "?tier=7", "?sort=answers", "?repeat=no"]
    )
    def test_a_value_that_is_not_on_offer_shows_everything(self, client, admin, three, query):
        assert len(names(client, query)) == 3

    def test_a_withdrawn_licence_is_said_and_has_no_level(self, client, admin, three):
        licences.revoke(three["alice"].entitlement)
        body = text(client, TABLE)
        alice = body.split(f'data-response="{three["alice"].pk}"')[1].split("</li>")[0]
        assert "Free (licence withdrawn)" in alice and "Tier 3" not in alice
        assert names(client, "?tier=3") == []

    def test_the_address_is_the_one_the_organization_knows_the_member_by(self, client, acme, admin):
        account = verified_account("dana@home.example.com")
        accounts.set_full_name(account, "Dana Example")
        from .test_profile import second_email

        second_email(account, "dana@work.example.com")
        invite, _sent = orgs.invite_by_email(acme[1], "dana@work.example.com")
        membership = orgs.accept_invite(invite.token, account)
        grant(membership)
        started(membership)
        body = text(client, TABLE)
        assert "dana@work.example.com" in body and "dana@home.example.com" not in body

    def test_someone_who_has_left_is_marked(self, client, acme, admin, three):
        carol = three["carol"].membership
        orgs.deactivate_membership(carol, by=acme[1])
        body = text(client, TABLE)
        assert body.count("(no longer a member)") == 1
        assert "Carol Example" in body  # what they submitted stays
        # Bob's unfinished attempt would be deleted with him.
        orgs.deactivate_membership(three["bob"].membership, by=acme[1])
        assert "Bob Example" not in text(client, TABLE)

    def test_the_pages_only_show_things(self, client, admin, three):
        """Nothing here can be changed: any request but a GET is refused."""
        assert client.post(TABLE).status_code == 405
        assert client.post(f"{TABLE}{three['bob'].pk}/").status_code == 405


@pytest.mark.django_db
class TestOneResponse:
    def address(self, response):
        return f"{TABLE}{response.pk}/"

    def test_a_submitted_one(self, client, admin, three):
        body = text(client, self.address(three["alice"]))
        for said in (
            "Alice Example",
            "alice@example.com",
            "Submitted",
            "Tier 3",
            "Possible repeat",
        ):
            assert said in body
        assert "Results will appear here in a later update." in body
        assert "never shown to an organization" in body
        assert f'href="{TABLE}"' in body and f'href="{ACME}"' in body

    def test_one_in_progress(self, client, admin, three):
        body = text(client, self.address(three["bob"]))
        assert "In progress" in body and "Not yet" in body
        assert "There are no results until the survey is submitted." in body

    def test_a_possible_repeat_and_a_withdrawn_licence(self, client, admin, three):
        Response.objects.filter(pk=three["carol"].pk).update(possible_repeat=True)
        licences.revoke(three["carol"].entitlement)
        body = text(client, self.address(three["carol"]))
        assert "it looks as though this person has taken the survey before" in body
        assert "Free (licence withdrawn)" in body
        assert "The licence for this survey was withdrawn" in body

    def test_an_id_that_does_not_exist_is_not_found(self, client, admin):
        assert client.get(f"{TABLE}424242/").status_code == 404


@pytest.mark.django_db
class TestTheWayIn:
    def test_the_admins_dashboard_links_to_the_table(self, client, admin):
        assert f'href="{TABLE}"' in text(client, ACME)

    def test_a_members_dashboard_does_not(self, client, acme):
        client.force_login(new_member(acme[0], "bob@example.com").account)
        body = text(client, ACME)
        assert TABLE not in body and "See responses" not in body
