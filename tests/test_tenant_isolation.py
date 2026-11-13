"""
Tenant isolation: nothing of one organization is ever visible to another.
The most important tests in the project (Milestone 3), written before the
pages they protect.

The world: two organizations, Acme and Globex, each with one admin and two
members. Every member has submitted one survey for their organization (on a
tier 1 licence) and one personally (on a tier 3 licence), so a page that leaks
a personal survey has something to leak.

What must hold on every organization page:

* An admin sees their own organization and nothing of the other.
* Someone outside an organization cannot open any of its pages: the answer is
  "not found" (404, never 403), and it is the same answer as for an
  organization that does not exist, so nobody can find out which ones do.
* A member who is not an admin gets that same answer for the admin pages.
* No page shows a phone number, a survey taken personally, a statement or an
  answer. The views hand their templates plain values, never database objects,
  so a later template edit cannot print one by accident.

Each PR that adds organization pages adds its addresses to the lists below
(PR 8: the list, the dashboard and the members page; PR 9: codes and invites;
PR 11: the responses table).
"""

import re
from types import SimpleNamespace

import pytest
from django.db import models
from django.test.utils import ContextList

from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.enterprises.models import Membership
from apps.responses import services as surveys
from apps.survey.models import Question

from .orgs import new_member, org_with_admin
from .test_profile import verified_account
from .test_response_context import finish, fresh, grant, grant_personal

# Every test account is registered with this number (tests/test_profile.py).
PHONE_DIGITS = "9876543210"
ORGANIZATION_TIER = 1
PERSONAL_TIER = 3

# Pages of one organization, as the part of the address after /organizations/<slug>/.
MEMBER_PAGES = [""]  # any active member may open these
ADMIN_PAGES = ["members/"]  # only an admin may open these


def member_actions(membership):
    """The addresses that act on one membership (admin only), with what each is sent."""
    base = f"members/{membership.pk}/"
    return [
        (base + "deactivate/", {}),
        (base + "reactivate/", {}),
        (base + "role/", {"role": "admin"}),
    ]


def build(name):
    """One organization: an admin, two members, and each member's two surveys."""
    enterprise, admin = org_with_admin(name)
    accounts.set_full_name(admin.account, f"{name} Admin")
    members, organization_responses, personal_responses = [], [], []
    for number in ("One", "Two"):
        member = new_member(enterprise, f"{number.lower()}@{enterprise.slug}.example.com")
        accounts.set_full_name(member.account, f"{name} Member{number}")
        grant(member, ORGANIZATION_TIER)
        grant_personal(member.account, PERSONAL_TIER)
        organization_responses.append(finish(surveys.start_response(member.account, member)))
        personal_responses.append(finish(surveys.start_response(member.account)))
        members.append(member)
    return SimpleNamespace(
        enterprise=enterprise,
        slug=enterprise.slug,
        admin=admin,
        members=members,
        everyone=[admin, *members],
        responses=organization_responses,
        personal=personal_responses,
    )


@pytest.fixture
def world(db):
    return SimpleNamespace(acme=build("Acme"), globex=build("Globex"))


def address(org, page=""):
    return f"/organizations/{org.slug}/{page}"


def html(client, url):
    page = client.get(url)
    assert page.status_code == 200, f"{url} answered {page.status_code}"
    return page.content.decode()


def settled(text):
    """A page's text without the security token, which is different on every load."""
    return re.sub(r"[A-Za-z0-9]{64}", "", text)


def everything_about(org):
    """Every name and email of an organization's people, and its own name."""
    words = [org.enterprise.name]
    for membership in org.everyone:
        words += [membership.account.full_name, membership.account.email]
    return words


def database_objects_given_to(page):
    """Every database object a view handed to its template. There should be none."""
    # What Django itself adds to every page (the logged-in user and so on).
    standard = {"user", "request", "perms", "messages", "csrf_token", "DEFAULT_MESSAGE_LEVELS"}
    found, seen = [], set()

    def walk(value):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, models.Model):
            found.append(value)
        elif isinstance(value, dict):
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list | tuple | set | models.QuerySet):
            for inner in value:
                walk(inner)

    contexts = page.context if isinstance(page.context, ContextList) else [page.context]
    for context in contexts:
        for key, value in context.flatten().items():
            if key not in standard:
                walk(value)
    return found


# --- an admin sees their own organization and nothing of the other -------------


@pytest.mark.django_db
class TestAnAdminSeesOnlyTheirOwnOrganization:
    def test_no_page_mentions_the_other_organization(self, client, world):
        client.force_login(world.acme.admin.account)
        pages = ["/organizations/"] + [address(world.acme, p) for p in MEMBER_PAGES + ADMIN_PAGES]
        for url in pages:
            text = html(client, url)
            assert "Acme" in text, url
            for word in everything_about(world.globex):
                assert word not in text, f"{url} shows something of the other organization"
            assert "globex" not in text.lower(), url

    def test_the_members_page_lists_exactly_its_own_people(self, client, world):
        client.force_login(world.acme.admin.account)
        text = html(client, address(world.acme, "members/"))
        for membership in world.acme.everyone:
            assert membership.account.full_name in text
            assert membership.account.email in text

    def test_the_counts_are_its_own(self, client, world):
        new_member(world.globex.enterprise, "extra@globex.example.com")
        client.force_login(world.acme.admin.account)
        page = client.get(address(world.acme))
        assert page.context["current_members"] == 3
        assert page.context["all_time_members"] == 3

    def test_the_other_organizations_member_cannot_be_acted_on(self, client, world):
        """Their own slug with someone else's membership id: not found, and nothing changes."""
        client.force_login(world.acme.admin.account)
        victim = world.globex.members[0]
        for page, data in member_actions(victim):
            assert client.post(address(world.acme, page), data).status_code == 404, page
            assert client.get(address(world.acme, page)).status_code in (404, 405), page
        victim = fresh(victim)
        assert victim.is_active and not victim.is_admin

    def test_nor_can_it_be_acted_on_under_its_own_slug(self, client, world):
        client.force_login(world.acme.admin.account)
        victim = world.globex.members[0]
        for page, data in member_actions(victim):
            assert client.post(address(world.globex, page), data).status_code == 404, page
        victim = fresh(victim)
        assert victim.is_active and not victim.is_admin


# --- outsiders get "not found" ---------------------------------------------------


@pytest.mark.django_db
class TestOutsidersGetNotFound:
    @pytest.fixture(params=["the other admin", "the other member", "nobody's member"])
    def outsider(self, request, client, world):
        account = {
            "the other admin": lambda: world.globex.admin.account,
            "the other member": lambda: world.globex.members[0].account,
            "nobody's member": lambda: verified_account("stranger@example.com"),
        }[request.param]()
        client.force_login(account)
        return account

    def test_every_page_is_not_found(self, client, world, outsider):
        for page in MEMBER_PAGES + ADMIN_PAGES:
            assert client.get(address(world.acme, page)).status_code == 404, page

    def test_every_action_is_not_found_and_changes_nothing(self, client, world, outsider):
        target = world.acme.members[0]
        for page, data in member_actions(target):
            assert client.post(address(world.acme, page), data).status_code == 404, page
        target = fresh(target)
        assert target.is_active and not target.is_admin

    def test_it_looks_exactly_like_an_organization_that_does_not_exist(
        self, client, world, outsider
    ):
        for page in MEMBER_PAGES + ADMIN_PAGES:
            real = client.get(address(world.acme, page))
            missing = client.get(f"/organizations/no-such-place/{page}")
            assert real.status_code == missing.status_code == 404
            assert real.content == missing.content

    def test_their_own_list_does_not_mention_it(self, client, world, outsider):
        text = html(client, "/organizations/")
        for word in everything_about(world.acme):
            assert word not in text


@pytest.mark.django_db
class TestFormerMembersAndStrangers:
    def test_a_deactivated_member_is_an_outsider(self, client, world):
        gone = world.acme.members[0]
        orgs.deactivate_membership(gone, by=world.acme.admin)
        client.force_login(gone.account)
        for page in MEMBER_PAGES + ADMIN_PAGES:
            assert client.get(address(world.acme, page)).status_code == 404, page
        assert "Acme" not in html(client, "/organizations/")

    def test_a_deactivated_admin_is_an_outsider(self, client, world):
        second = world.acme.members[0]
        orgs.set_role(second, "admin", by=world.acme.admin)
        orgs.deactivate_membership(world.acme.admin, by=fresh(second))
        client.force_login(world.acme.admin.account)
        target = world.acme.members[1]
        for page in MEMBER_PAGES + ADMIN_PAGES:
            assert client.get(address(world.acme, page)).status_code == 404, page
        for page, data in member_actions(target):
            assert client.post(address(world.acme, page), data).status_code == 404, page
        assert fresh(target).is_active

    def test_a_logged_out_visitor_is_sent_to_log_in(self, client, world):
        urls = ["/organizations/", "/organizations/new/"]
        urls += [address(world.acme, page) for page in MEMBER_PAGES + ADMIN_PAGES]
        for url in urls:
            page = client.get(url)
            assert page.status_code == 302 and "/accounts/login/" in page.url, url
        for page, data in member_actions(world.acme.members[0]):
            answer = client.post(address(world.acme, page), data)
            assert answer.status_code == 302 and "/accounts/login/" in answer.url, page
        assert fresh(world.acme.members[0]).is_active


# --- a member is not an admin ----------------------------------------------------


@pytest.mark.django_db
class TestAMemberIsNotAnAdmin:
    @pytest.fixture
    def member(self, client, world):
        client.force_login(world.acme.members[0].account)
        return world.acme.members[0]

    def test_the_admin_pages_are_not_found(self, client, world, member):
        for page in ADMIN_PAGES:
            real = client.get(address(world.acme, page))
            missing = client.get(f"/organizations/no-such-place/{page}")
            assert real.status_code == 404 and real.content == missing.content, page

    def test_the_actions_are_not_found_and_change_nothing(self, client, world, member):
        other = world.acme.members[1]
        for target in (other, member, world.acme.admin):
            for page, data in member_actions(target):
                assert client.post(address(world.acme, page), data).status_code == 404, page
        assert fresh(other).is_active and not fresh(other).is_admin
        assert not fresh(member).is_admin
        assert fresh(world.acme.admin).is_active

    def test_the_member_pages_show_nobody_else(self, client, world, member):
        """A member sees the organization's name and their own things, never other members."""
        others = [m for m in world.acme.everyone if m.pk != member.pk]
        for url in ["/organizations/"] + [address(world.acme, page) for page in MEMBER_PAGES]:
            page = client.get(url)
            text = page.content.decode()
            assert page.status_code == 200 and "Acme" in text, url
            for membership in others:
                assert membership.account.full_name not in text, url
                assert membership.account.email not in text, url
            assert "current_members" not in page.context, url
            assert "all_time_members" not in page.context, url


# --- what no organization page ever shows ----------------------------------------


@pytest.mark.django_db
class TestWhatNoPageShows:
    def pages_of(self, client, world):
        """Every page of Acme, opened by its admin (who can open them all)."""
        client.force_login(world.acme.admin.account)
        urls = ["/organizations/", "/organizations/new/"]
        urls += [address(world.acme, page) for page in MEMBER_PAGES + ADMIN_PAGES]
        urls.append(address(world.acme, f"members/{world.acme.members[0].pk}/deactivate/"))
        for url in urls:
            page = client.get(url)
            assert page.status_code == 200, url
            yield url, page, page.content.decode()

    def test_never_a_phone_number(self, client, world):
        for url, _page, text in self.pages_of(client, world):
            digits = "".join(character for character in text if character.isdigit())
            assert PHONE_DIGITS not in digits, url

    def test_never_a_statement(self, client, world):
        statements = list(Question.objects.values_list("text", flat=True))
        assert statements
        for url, _page, text in self.pages_of(client, world):
            for statement in statements:
                assert statement not in text, url

    def test_never_a_database_object_in_the_template(self, client, world):
        """Plain values only: so no template can reach an answer or a phone number."""
        for url, page, _text in self.pages_of(client, world):
            assert database_objects_given_to(page) == [], url

    def test_the_licence_shown_is_the_organizations_never_a_personal_one(self, client, world):
        client.force_login(world.acme.admin.account)
        page = client.get(address(world.acme, "members/"))
        tiers = {row["tier"] for row in page.context["rows"]}
        assert tiers == {None, ORGANIZATION_TIER}  # the admin has no licence
        assert f"Tier {PERSONAL_TIER}" not in page.content.decode()

    def test_a_personal_survey_changes_nothing_on_any_page(self, client, world):
        """The pages read the same before and after a member takes a survey personally."""
        client.force_login(world.acme.admin.account)
        urls = [address(world.acme, page) for page in MEMBER_PAGES + ADMIN_PAGES]
        before = [settled(html(client, url)) for url in urls]
        member = world.acme.members[0]
        grant_personal(member.account, 2)
        finish(surveys.start_response(member.account))
        assert [settled(html(client, url)) for url in urls] == before

    def test_the_fixture_really_has_both_kinds_of_survey(self, world):
        for org in (world.acme, world.globex):
            assert all(r.status == "submitted" and r.membership_id for r in org.responses)
            assert all(r.status == "submitted" and r.membership_id is None for r in org.personal)
            assert Membership.objects.filter(enterprise=org.enterprise).count() == 3
