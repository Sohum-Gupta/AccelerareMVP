"""
Tenant isolation: nothing of one organization is ever visible to another.
The most important tests in the project (Milestone 3), written before the
pages they protect.

The world: two organizations, Acme and Globex, each with one admin and two
members. Every member has submitted one survey for their organization (on a
tier 1 licence) and one personally (on a tier 3 licence), so a page that leaks
a personal survey has something to leak. Each organization also has a join
code and an invite that is still open.

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
PR 11: the responses table and the page of one response; Milestone 4, PR 3:
the Licences page, its three actions and the "take back" confirmation page).

The responses pages are where a survey first appears on an organization page,
so they get a class of their own at the bottom: an admin sees the surveys
taken for their organization, never one taken personally or for anyone else,
and of each one only who, when, its status and its level. Never an answer.

The Licences page (Milestone 4) is where an admin gives out the organization's
stock, so it has a class too: the stock and the members are its own, and a
licence or a member of another organization (or a member's personal licence)
is "not found" to every button on it.

Each organization has bought three Tier 2 and two Tier 3 licences, and its
second member holds an unused Tier 2 one from that stock.
"""

import re
from types import SimpleNamespace

import pytest
from django.db import models
from django.test.utils import ContextList

from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.enterprises.models import Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.responses import services as surveys
from apps.survey.models import Question

from .orgs import new_member, org_with_admin
from .test_profile import verified_account
from .test_response_context import finish, fresh, grant, grant_personal

# Every test account is registered with this number (tests/test_profile.py).
PHONE_DIGITS = "9876543210"
ORGANIZATION_TIER = 1
PERSONAL_TIER = 3
# What each organization has bought, and the tier of the one licence given from it.
STOCK = {2: 3, 3: 2}
STOCK_TIER = 2

# Pages of one organization, as the part of the address after /organizations/<slug>/.
MEMBER_PAGES = [""]  # any active member may open these
# Only an admin may open these.
ADMIN_PAGES = ["members/", "codes/", "invites/", "responses/", "licences/"]
# Forms on those pages that make something new (admin only), with what each is sent.
ADMIN_FORMS = [
    ("codes/", {"max_uses": "5", "days": "30"}),
    ("invites/", {"email": "someone.new@example.com"}),
]


def response_page(response):
    """The page of one response (admin only), as the part after /organizations/<slug>/."""
    return f"responses/{response.pk}/"


def take_back_page(licence):
    """The page that asks before a licence is taken back (admin only), and takes it back."""
    return f"licences/{licence.pk}/take-back/"


def admin_pages(org):
    """Every admin page of an organization, including those about one response or licence."""
    return [*ADMIN_PAGES, response_page(org.responses[0]), take_back_page(org.seat)]


def member_actions(membership):
    """The addresses that act on one membership (admin only), with what each is sent."""
    base = f"members/{membership.pk}/"
    return [
        (base + "deactivate/", {}),
        (base + "reactivate/", {}),
        (base + "role/", {"role": "admin"}),
    ]


def licence_actions(org):
    """
    The buttons of the Licences page (admin only), with what each is sent. Each
    would succeed if its organization's own admin pressed it: the first member
    can be given a licence, and the stock has a Tier 3 to move the licence to.
    """
    return [
        (f"licences/members/{org.members[0].pk}/give/", {"tier": str(STOCK_TIER)}),
        (f"licences/{org.seat.pk}/tier/", {"tier": "3"}),
        (take_back_page(org.seat), {}),
    ]


def actions_on(org):
    """Every address that changes one of an organization's own things, by its id."""
    return [
        *member_actions(org.members[0]),
        (f"codes/{org.code.pk}/revoke/", {}),
        (f"invites/{org.invite.pk}/resend/", {}),
        (f"invites/{org.invite.pk}/move/", {"email": "moved@example.com"}),
        (f"invites/{org.invite.pk}/revoke/", {}),
        *licence_actions(org),
    ]


def licences_of(org):
    """Every licence for the organization, taken back or not. Never a personal one."""
    return Entitlement.objects.filter(membership__enterprise=org.enterprise)


def same_invite(invite):
    """True if the invite still goes to the same address, by the same link, emailed as often."""
    now = fresh(invite)
    return (now.email, now.token, now.emails_sent) == (
        invite.email,
        invite.token,
        invite.emails_sent,
    )


def untouched(org):
    """True if nothing of the organization's has been changed or added to."""
    member = fresh(org.members[0])
    seat = fresh(org.seat)
    return (
        member.is_active
        and not member.is_admin
        and fresh(org.code).revoked_at is None
        and fresh(org.invite).revoked_at is None
        and same_invite(org.invite)
        and org.enterprise.join_codes.count() == 1
        and org.enterprise.invites.count() == 1
        and seat.revoked_at is None
        and seat.tier == STOCK_TIER
        and licences_of(org).count() == 3  # one each from staff, and the one from the stock
    )


def build(name):
    """
    One organization: an admin, two members with two surveys each, a code, an
    invite, a stock of licences and one licence given from it.
    """
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
    invite, _sent = orgs.invite_by_email(admin, f"invited@{enterprise.slug}.example.com")
    for tier, bought in STOCK.items():
        orgs.set_seat_pool(enterprise, tier, bought)
    return SimpleNamespace(
        enterprise=enterprise,
        slug=enterprise.slug,
        admin=admin,
        members=members,
        everyone=[admin, *members],
        responses=organization_responses,
        personal=personal_responses,
        code=orgs.create_code(admin, 5),
        invite=invite,
        # The second member's, unused. The first can still be given one.
        seat=licences.assign_seat(admin, members[1], STOCK_TIER),
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
    """Its name, every name and email of its people, and its code and invite."""
    words = [org.enterprise.name]
    for membership in org.everyone:
        words += [membership.account.full_name, membership.account.email]
    words += [org.code.code, orgs.display_code(org.code.code), org.invite.email, org.invite.token]
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
        pages = ["/organizations/"]
        pages += [address(world.acme, p) for p in MEMBER_PAGES + admin_pages(world.acme)]
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

    def test_the_codes_and_invites_pages_list_exactly_its_own(self, client, world):
        client.force_login(world.acme.admin.account)
        assert orgs.display_code(world.acme.code.code) in html(
            client, address(world.acme, "codes/")
        )
        text = html(client, address(world.acme, "invites/"))
        assert world.acme.invite.email in text and world.acme.invite.token in text

    def test_the_places_left_are_its_own(self, client, world):
        """Globex bringing people in uses none of Acme's places."""
        for number in range(3):
            orgs.invite_by_email(world.globex.admin, f"more{number}@globex.example.com")
        orgs.redeem_code(world.globex.code.code, verified_account("joiner@example.com"))
        client.force_login(world.acme.admin.account)
        orgs.set_seat_pool(world.globex.enterprise, 1, 40)
        for page in ("", "codes/", "invites/"):
            places = client.get(address(world.acme, page)).context["places"]
            # 25 and the five licences Acme has bought; Acme has sent one invite.
            assert places == {"left": 29, "limit": 30}, page

    def test_the_other_organizations_things_cannot_be_acted_on(self, client, world):
        """Their own slug with someone else's id: not found, and nothing changes."""
        client.force_login(world.acme.admin.account)
        for page, data in actions_on(world.globex):
            assert client.post(address(world.acme, page), data).status_code == 404, page
            assert client.get(address(world.acme, page)).status_code in (404, 405), page
        assert untouched(world.globex)

    def test_nor_can_they_be_acted_on_under_their_own_slug(self, client, world):
        client.force_login(world.acme.admin.account)
        for page, data in actions_on(world.globex) + ADMIN_FORMS:
            assert client.post(address(world.globex, page), data).status_code == 404, page
        assert untouched(world.globex)


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
        for page in MEMBER_PAGES + admin_pages(world.acme):
            assert client.get(address(world.acme, page)).status_code == 404, page

    def test_every_action_is_not_found_and_changes_nothing(self, client, world, outsider):
        for page, data in actions_on(world.acme) + ADMIN_FORMS:
            assert client.post(address(world.acme, page), data).status_code == 404, page
        assert untouched(world.acme)

    def test_it_looks_exactly_like_an_organization_that_does_not_exist(
        self, client, world, outsider
    ):
        for page in MEMBER_PAGES + admin_pages(world.acme):
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
        for page in MEMBER_PAGES + admin_pages(world.acme):
            assert client.get(address(world.acme, page)).status_code == 404, page
        assert "Acme" not in html(client, "/organizations/")

    def test_a_deactivated_admin_is_an_outsider(self, client, world):
        second = world.acme.members[0]
        orgs.set_role(second, "admin", by=world.acme.admin)
        orgs.deactivate_membership(world.acme.admin, by=fresh(second))
        client.force_login(world.acme.admin.account)
        target = world.acme.members[1]
        for page in MEMBER_PAGES + admin_pages(world.acme):
            assert client.get(address(world.acme, page)).status_code == 404, page
        posts = member_actions(target) + actions_on(world.acme)[3:] + ADMIN_FORMS
        for page, data in posts:
            assert client.post(address(world.acme, page), data).status_code == 404, page
        assert fresh(target).is_active
        assert fresh(world.acme.code).revoked_at is None
        assert world.acme.enterprise.invites.count() == 1

    def test_a_logged_out_visitor_is_sent_to_log_in(self, client, world):
        urls = ["/organizations/", "/organizations/new/"]
        urls += [address(world.acme, page) for page in MEMBER_PAGES + admin_pages(world.acme)]
        for url in urls:
            page = client.get(url)
            assert page.status_code == 302 and "/accounts/login/" in page.url, url
        for page, data in actions_on(world.acme) + ADMIN_FORMS:
            answer = client.post(address(world.acme, page), data)
            assert answer.status_code == 302 and "/accounts/login/" in answer.url, page
        assert untouched(world.acme)


# --- a member is not an admin ----------------------------------------------------


@pytest.mark.django_db
class TestAMemberIsNotAnAdmin:
    @pytest.fixture
    def member(self, client, world):
        client.force_login(world.acme.members[0].account)
        return world.acme.members[0]

    def test_the_admin_pages_are_not_found(self, client, world, member):
        for page in admin_pages(world.acme):
            real = client.get(address(world.acme, page))
            missing = client.get(f"/organizations/no-such-place/{page}")
            assert real.status_code == 404 and real.content == missing.content, page

    def test_the_actions_are_not_found_and_change_nothing(self, client, world, member):
        other = world.acme.members[1]
        for target in (other, member, world.acme.admin):
            for page, data in member_actions(target):
                assert client.post(address(world.acme, page), data).status_code == 404, page
        for page, data in actions_on(world.acme) + ADMIN_FORMS:
            assert client.post(address(world.acme, page), data).status_code == 404, page
        assert fresh(other).is_active and not fresh(other).is_admin
        assert fresh(world.acme.admin).is_active
        assert untouched(world.acme)

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
            admin_things = ("current_members", "all_time_members", "places", "stock")
            for admins_only in admin_things:
                assert admins_only not in page.context, url
            for secret in (world.acme.code.code, world.acme.invite.email, world.acme.invite.token):
                assert secret not in text, url
            assert orgs.display_code(world.acme.code.code) not in text, url


# --- what no organization page ever shows ----------------------------------------


@pytest.mark.django_db
class TestWhatNoPageShows:
    def pages_of(self, client, world):
        """Every page of Acme, opened by its admin (who can open them all)."""
        client.force_login(world.acme.admin.account)
        urls = ["/organizations/", "/organizations/new/"]
        urls += [address(world.acme, page) for page in MEMBER_PAGES + admin_pages(world.acme)]
        urls.append(address(world.acme, f"members/{world.acme.members[0].pk}/deactivate/"))
        for url in urls:
            page = client.get(url)
            assert page.status_code == 200, url
            yield url, page, page.content.decode()

    def test_the_licences_page_is_among_them(self, client, world):
        urls = [url for url, _page, _text in self.pages_of(client, world)]
        assert address(world.acme, "licences/") in urls
        assert address(world.acme, take_back_page(world.acme.seat)) in urls

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
        # The admin has no licence; the second member's highest is the one from the stock.
        assert tiers == {None, ORGANIZATION_TIER, STOCK_TIER}
        assert f"Tier {PERSONAL_TIER}" not in page.content.decode()

    def test_a_personal_survey_changes_nothing_on_any_page(self, client, world):
        """The pages read the same before and after a member takes a survey personally."""
        client.force_login(world.acme.admin.account)
        urls = [address(world.acme, page) for page in MEMBER_PAGES + admin_pages(world.acme)]
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
            assert orgs.seat_summary(org.enterprise) == [
                {"tier": 1, "bought": 0, "given": 0, "set_aside": 0, "left": 0},
                {"tier": 2, "bought": 3, "given": 1, "set_aside": 0, "left": 2},
                {"tier": 3, "bought": 2, "given": 0, "set_aside": 0, "left": 2},
            ]
            assert org.seat.source == "seat" and org.seat.membership == org.members[1]


# --- the responses pages ---------------------------------------------------------

# Everything an admin is told about one response. Nothing else may be added
# without the founder's say: this list is the promise the disclosure page makes.
RESPONSE_FACTS = {
    "id",
    "name",
    "email",
    "erased",
    "member_active",
    "submitted",
    "started_at",
    "submitted_at",
    "tier",
    "withdrawn",
    "possible_repeat",
}


@pytest.mark.django_db
class TestTheResponsesPages:
    @pytest.fixture
    def admin(self, client, world):
        client.force_login(world.acme.admin.account)
        return world.acme.admin

    def shown(self, client, world):
        return client.get(address(world.acme, "responses/")).context["rows"]

    def test_the_table_lists_exactly_the_surveys_taken_for_the_organization(
        self, client, world, admin
    ):
        ids = {row["id"] for row in self.shown(client, world)}
        assert ids == {response.pk for response in world.acme.responses}
        text = html(client, address(world.acme, "responses/"))
        for member in world.acme.members:
            assert member.account.full_name in text and member.account.email in text

    def test_a_survey_taken_personally_is_never_listed(self, client, world, admin):
        """Not even while it is being taken, and not in the count."""
        member = world.acme.members[0]
        grant_personal(member.account, PERSONAL_TIER)
        surveys.start_response(member.account)
        page = client.get(address(world.acme, "responses/"))
        assert {row["id"] for row in page.context["rows"]} == {r.pk for r in world.acme.responses}
        assert page.context["total"] == 2

    def test_every_filter_and_order_still_lists_only_its_own(self, client, world, admin):
        own = {response.pk for response in world.acme.responses}
        for query in (
            "?status=submitted",
            "?status=draft",
            f"?tier={ORGANIZATION_TIER}",
            f"?tier={PERSONAL_TIER}",
            "?repeat=yes",
            "?sort=member",
            "?sort=started",
            "?sort=-submitted",
            "?status=nonsense&tier=9&sort=answers",
        ):
            page = client.get(address(world.acme, "responses/") + query)
            assert page.status_code == 200, query
            assert {row["id"] for row in page.context["rows"]} <= own, query
            assert database_objects_given_to(page) == [], query

    def test_another_organizations_response_is_not_found(self, client, world, admin):
        missing = client.get(address(world.acme, "responses/999999/"))
        assert missing.status_code == 404
        for response in world.globex.responses + world.globex.personal:
            for org in (world.acme, world.globex):
                page = client.get(address(org, response_page(response)))
                assert page.status_code == 404, "404, never 403"
        # The same answer as for a response that does not exist at all.
        theirs = client.get(address(world.acme, response_page(world.globex.responses[0])))
        assert theirs.content == missing.content

    def test_a_members_personal_survey_is_not_found(self, client, world, admin):
        for response in world.acme.personal:
            page = client.get(address(world.acme, response_page(response)))
            assert page.status_code == 404

    def test_the_page_of_one_response_is_about_that_response_only(self, client, world, admin):
        first, second = world.acme.members
        page = client.get(address(world.acme, response_page(world.acme.responses[0])))
        text = page.content.decode()
        assert first.account.full_name in text and first.account.email in text
        assert second.account.full_name not in text and second.account.email not in text
        assert page.context["row"]["id"] == world.acme.responses[0].pk

    def test_an_admin_is_told_only_the_agreed_facts(self, client, world, admin):
        for row in self.shown(client, world):
            assert set(row) == RESPONSE_FACTS
        page = client.get(address(world.acme, response_page(world.acme.responses[0])))
        assert set(page.context["row"]) == RESPONSE_FACTS

    def test_never_the_self_report_or_how_far_a_draft_has_got(self, client, world, admin):
        """A draft with a "yes, through my company" self-report and two pages locked."""
        member = new_member(world.acme.enterprise, "three@acme.example.com")
        grant(member, 2)
        draft = surveys.save_self_report(
            surveys.start_response(member.account, member), True, "company"
        )
        questions = Question.objects.filter(survey_version=draft.survey_version)
        for question in questions.order_by("position")[:10]:
            draft = surveys.save_answer(draft, question.pk, 4)
            if question.position % 5 == 0:
                draft = surveys.complete_page(draft, question.position // 5)
        assert draft.pages_completed == 2 and draft.took_before
        before = html(client, address(world.acme, "responses/"))

        for url in ("responses/", response_page(draft)):
            text = html(client, address(world.acme, url)).split("<main")[1]
            assert "In progress" in text
            for leak in (
                "ompany",
                "taken this survey before?",
                "Page 2",
                "page 3",
                "2 of 5",
                "10 of",
            ):
                assert leak not in text, f"{url} shows {leak!r}"

        # Answering more changes nothing an admin can see.
        for question in questions.order_by("position")[10:15]:
            draft = surveys.save_answer(draft, question.pk, 1)
        surveys.complete_page(draft, 3)
        assert settled(html(client, address(world.acme, "responses/"))) == settled(before)

    def test_the_answers_are_not_even_read_from_the_database(self, client, world, admin):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for url in ("responses/", response_page(world.acme.responses[0])):
            with CaptureQueriesContext(connection) as queries:
                html(client, address(world.acme, url))
            about_responses = [q["sql"] for q in queries if "responses_response" in q["sql"]]
            assert about_responses, url
            for sql in about_responses:
                for column in ("answers", "took_before", "took_before_via", "pages_completed"):
                    assert f'"{column}"' not in sql, f"{url} reads {column}"

    def test_a_deactivated_members_survey_stays_and_an_erased_member_has_no_name(
        self, client, world, admin
    ):
        from apps.accounts import erasure

        gone, erased = world.acme.members
        orgs.deactivate_membership(gone, by=world.acme.admin)
        name, email = erased.account.full_name, erased.account.email
        erasure.erase_account(erased.account)
        text = html(client, address(world.acme, "responses/"))
        assert len(self.shown(client, world)) == 2
        assert gone.account.full_name in text
        assert "Erased member" in text and name not in text and email not in text


# --- the Licences page -----------------------------------------------------------

# Everything the Licences page is told about a member and about one licence.
LICENCE_MEMBER_FACTS = {
    "id",
    "name",
    "email",
    "erased",
    "active",
    "is_you",
    "can_give",
    "licences",
}
LICENCE_FACTS = {"id", "tier", "state", "from_stock", "can_take_back", "move_to"}
# The stock lines Acme's admin is shown: only tiers it has bought.
ACME_STOCK = [
    {"tier": 2, "bought": 3, "given": 1, "set_aside": 0, "left": 2},
    {"tier": 3, "bought": 2, "given": 0, "set_aside": 0, "left": 2},
]


@pytest.mark.django_db
class TestTheLicencesPage:
    @pytest.fixture
    def admin(self, client, world):
        client.force_login(world.acme.admin.account)
        return world.acme.admin

    def page(self, client, world):
        return client.get(address(world.acme, "licences/"))

    def shown_licences(self, client, world):
        rows = self.page(client, world).context["rows"]
        return {licence["id"] for row in rows for licence in row["licences"]}

    def test_it_lists_exactly_its_own_members_and_their_licences(self, client, world, admin):
        page = self.page(client, world)
        assert {row["id"] for row in page.context["rows"]} == {m.pk for m in world.acme.everyone}
        own = set(licences_of(world.acme).values_list("pk", flat=True))
        assert self.shown_licences(client, world) == own and len(own) == 3
        text = page.content.decode()
        for membership in world.acme.everyone:
            assert membership.account.full_name in text and membership.account.email in text

    def test_a_personal_licence_is_never_listed(self, client, world, admin):
        """Not one already used, and not one a member has just been given."""
        before = self.shown_licences(client, world)
        text = settled(html(client, address(world.acme, "licences/")))
        new = grant_personal(world.acme.members[0].account, 2)
        assert self.shown_licences(client, world) == before
        assert new.pk not in before
        assert settled(html(client, address(world.acme, "licences/"))) == text
        personal = Entitlement.objects.filter(membership__isnull=True)
        assert not before & set(personal.values_list("pk", flat=True))

    def test_the_stock_is_its_own(self, client, world, admin):
        """Whatever Globex buys, gives and takes back, Acme's numbers stay as they were."""
        before = settled(html(client, address(world.acme, "licences/")))
        orgs.set_seat_pool(world.globex.enterprise, 2, 50)
        orgs.set_seat_pool(world.globex.enterprise, 1, 7)
        licences.assign_seat(world.globex.admin, world.globex.members[0], 1)
        licences.take_back_seat(world.globex.admin, world.globex.seat)
        for url in ("licences/", ""):
            assert client.get(address(world.acme, url)).context["stock"] == ACME_STOCK, url
        assert settled(html(client, address(world.acme, "licences/"))) == before

    def test_what_another_organization_sets_aside_is_its_own(self, client, world, admin):
        """Globex promising its licences to a code and an invite takes nothing from Acme's stock."""
        orgs.create_code(world.globex.admin, 2, tier=3)
        orgs.invite_by_email(world.globex.admin, "late@example.com", tier=2)
        assert orgs.seats_set_aside(world.globex.enterprise) == {1: 0, 2: 1, 3: 2}
        assert orgs.seats_set_aside(world.acme.enterprise) == {1: 0, 2: 0, 3: 0}
        for url in ("licences/", ""):
            page = client.get(address(world.acme, url))
            assert page.context["stock"] == ACME_STOCK, url
            assert "data-set-aside" not in page.content.decode(), url

    def test_another_organizations_member_cannot_be_given_a_licence(self, client, world, admin):
        for member in world.globex.everyone:
            for org in (world.acme, world.globex):
                answer = client.post(
                    address(org, f"licences/members/{member.pk}/give/"), {"tier": "2"}
                )
                assert answer.status_code == 404, "404, never 403"
        assert licences_of(world.globex).count() == 3
        assert orgs.seat_summary(world.acme.enterprise)[1]["given"] == 1

    def test_a_licence_that_is_not_the_organizations_is_not_found(self, client, world, admin):
        """Another organization's, from its stock or from staff, and a member's personal one."""
        member = world.acme.members[0]
        not_ours = [
            world.globex.seat,
            licences_of(world.globex).exclude(pk=world.globex.seat.pk).first(),
            Entitlement.objects.filter(person=member.account.person).first(),
        ]
        missing = client.get(address(world.acme, "licences/999999/take-back/"))
        assert missing.status_code == 404
        for licence in not_ours:
            for org in (world.acme, world.globex):
                asks = client.get(address(org, take_back_page(licence)))
                assert asks.status_code == 404, "404, never 403"
                if org is world.acme:
                    # The same answer as for a licence that does not exist at all.
                    assert asks.content == missing.content
                assert client.post(address(org, take_back_page(licence))).status_code == 404
                change = address(org, f"licences/{licence.pk}/tier/")
                assert client.post(change, {"tier": "3"}).status_code == 404
            after = fresh(licence)
            assert after.revoked_at is None and after.tier == licence.tier
        assert untouched(world.globex)

    def test_an_admin_is_told_only_the_agreed_facts(self, client, world, admin):
        page = self.page(client, world)
        for row in page.context["rows"]:
            assert set(row) == LICENCE_MEMBER_FACTS
            for licence in row["licences"]:
                assert set(licence) == LICENCE_FACTS
        assert page.context["stock"] == ACME_STOCK
        asks = client.get(address(world.acme, take_back_page(world.acme.seat)))
        assert set(asks.context["licence"]) == {"id", "tier", "in_progress", "name"}

    def test_the_answers_are_not_even_read_from_the_database(self, client, world, admin):
        """The pages say whether a survey is in progress or submitted, from its status alone."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        holder = world.acme.members[1]
        surveys.start_response(holder.account, holder)
        for url in ("licences/", take_back_page(world.acme.seat)):
            with CaptureQueriesContext(connection) as queries:
                text = html(client, address(world.acme, url))
            about_responses = [q["sql"] for q in queries if "responses_response" in q["sql"]]
            assert about_responses, url
            for sql in about_responses:
                for column in ("answers", "took_before", "took_before_via", "pages_completed"):
                    assert f'"{column}"' not in sql, f"{url} reads {column}"
            assert "started" in text.lower() or "in progress" in text.lower(), url
