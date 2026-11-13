"""
Milestone 4, PR 4: a tier on an invite or a join code.

The rule (the founder's, 2026-11-13). The admin may choose a tier when sending
an invite or making a join code. Each person who joins with it is given a
licence of that tier out of the organization's stock. If none is left they
still join, without a licence, and the admin's pages say how many people that
happened to. A join never fails because of the stock.

How it is built. The organizations app may not import the licences app, so it
announces every join with a signal (`member_joined`) and the licences app
gives the licence. The listeners run inside a savepoint: if one fails, what it
wrote is undone and the person joins anyway.
"""

import logging

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.enterprises import services as orgs
from apps.enterprises.models import Invite, JoinCode, Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement

from .orgs import new_member, org_with_admin, run_together
from .test_profile import verified_account
from .test_response_context import fresh, grant
from .test_seat_pools import row as stock_line
from .test_seat_pools import take_survey
from .test_seat_services import LICENCE, MEMBERSHIP, ORGANIZATION, events, lock_order

ACME = "/organizations/acme/"
CODES = "/organizations/acme/codes/"
INVITES = "/organizations/acme/invites/"
LICENCES = "/organizations/acme/licences/"
CAROL = "carol@example.com"
NO_LICENCE = '<option value="" selected>No licence</option>'


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership), with two Tier 2 licences bought"""
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 2)
    return enterprise, admin


@pytest.fixture
def admin(client, acme):
    """Acme's admin, logged in. Returns the admin's membership."""
    client.force_login(acme[1].account)
    return acme[1]


def join_by_code(admin, email=CAROL, tier=2, **extra):
    """Someone new joins with a fresh code that carries this tier. Returns their membership."""
    code = orgs.create_code(admin, extra.pop("max_uses", 5), tier=tier)
    return orgs.redeem_code(code.code, verified_account(email))


def join_by_invite(admin, email=CAROL, tier=2):
    """Someone new accepts an invite that carries this tier. Returns their membership."""
    invite, _sent = orgs.invite_by_email(admin, email, tier=tier)
    return orgs.accept_invite(invite.token, verified_account(email))


def licences_of(membership):
    return list(Entitlement.objects.filter(membership=membership))


def html(client, address):
    page = client.get(address)
    assert page.status_code == 200, f"{address} answered {page.status_code}"
    return " ".join(page.content.decode().split())


def after(client, address, data=None):
    """Send a form and return the page the person lands on, as (address, text)."""
    page = client.post(address, data or {}, follow=True)
    assert page.status_code == 200
    return page.redirect_chain[-1][0], " ".join(page.content.decode().split())


# --- joining brings a licence --------------------------------------------------------


@pytest.mark.django_db
class TestJoiningBringsALicence:
    def test_a_code_with_a_tier_gives_whoever_joins_a_licence_from_the_stock(self, acme):
        enterprise, admin = acme
        member = join_by_code(admin)
        (licence,) = licences_of(member)
        assert (licence.tier, licence.source, licence.person) == (2, "seat", None)
        assert licence.is_active and licence.granted_by == admin.account  # who made the code
        assert stock_line(enterprise, 2) == {"tier": 2, "bought": 2, "given": 1, "left": 1}
        assert events() == [("licence_granted", 2, "seat")]
        assert licences.has_survey_access(member.account, member)

    def test_an_invite_with_a_tier_does_the_same(self, acme):
        enterprise, admin = acme
        member = join_by_invite(admin)
        (licence,) = licences_of(member)
        assert (licence.tier, licence.source, licence.granted_by) == (2, "seat", admin.account)
        assert stock_line(enterprise, 2)["given"] == 1
        assert events() == [("licence_granted", 2, "seat")]

    def test_without_a_tier_joining_gives_no_licence(self, acme):
        _, admin = acme
        for member in (
            join_by_code(admin, tier=None),
            join_by_invite(admin, "dan@example.com", tier=None),
        ):
            assert licences_of(member) == []
        assert events() == []
        assert orgs.joined_without_licence(acme[0]) == {}

    def test_each_person_who_joins_with_the_code_gets_one_while_the_stock_lasts(self, acme):
        enterprise, admin = acme
        code = orgs.create_code(admin, 5, tier=2)
        people = [
            orgs.redeem_code(code.code, verified_account(f"person{number}@example.com"))
            for number in range(3)
        ]
        assert [len(licences_of(person)) for person in people] == [1, 1, 0]
        assert stock_line(enterprise, 2) == {"tier": 2, "bought": 2, "given": 2, "left": 0}
        assert fresh(code).uses == 3

    def test_the_licence_counts_against_the_tier_it_names(self, acme):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 3, 1)
        member = join_by_code(admin, tier=3)
        assert [licence.tier for licence in licences_of(member)] == [3]
        assert stock_line(enterprise, 3)["left"] == 0 and stock_line(enterprise, 2)["left"] == 2

    def test_a_licence_staff_granted_does_not_use_up_the_stock_for_joiners(self, acme):
        enterprise, admin = acme
        for number in range(2):
            grant(new_member(enterprise, f"gift{number}@example.com"), 2)
        assert len(licences_of(join_by_code(admin))) == 1


# --- with none left, they still join -------------------------------------------------


@pytest.mark.django_db
class TestWithNoneLeftTheyStillJoin:
    @pytest.fixture
    def empty(self, acme):
        """Acme with no Tier 2 licence left."""
        orgs.set_seat_pool(acme[0], 2, 0)
        return acme

    def test_by_code(self, empty):
        enterprise, admin = empty
        member = join_by_code(admin)
        assert member.is_active and member.enterprise == enterprise
        assert licences_of(member) == [] and events() == []
        assert JoinCode.objects.get().uses == 1
        assert orgs.joined_without_licence(enterprise) == {member.pk: 2}

    def test_by_invite(self, empty):
        enterprise, admin = empty
        member = join_by_invite(admin)
        assert member.is_active and Invite.objects.get().accepted_at is not None
        assert licences_of(member) == []
        assert orgs.joined_without_licence(enterprise) == {member.pk: 2}

    def test_a_stock_of_another_tier_is_not_used_instead(self, empty):
        enterprise, admin = empty
        orgs.set_seat_pool(enterprise, 3, 5)
        member = join_by_code(admin)
        assert licences_of(member) == []
        assert orgs.joined_without_licence(enterprise) == {member.pk: 2}

    def test_they_stop_being_counted_once_they_are_given_a_licence(self, empty):
        enterprise, admin = empty
        member = join_by_code(admin)
        orgs.set_seat_pool(enterprise, 2, 1)
        assert orgs.joined_without_licence(enterprise) == {member.pk: 2}  # buying is not giving
        licence = licences.assign_seat(admin, member, 2)
        assert orgs.joined_without_licence(enterprise) == {}
        # Taking it back is the admin's decision: they are not counted again.
        licences.take_back_seat(admin, licence)
        assert orgs.joined_without_licence(enterprise) == {}

    def test_a_licence_from_staff_also_ends_it(self, empty):
        enterprise, admin = empty
        member = join_by_code(admin)
        grant(member, 1)
        assert orgs.joined_without_licence(enterprise) == {}

    def test_only_active_members_of_that_organization_are_counted(self, empty):
        enterprise, admin = empty
        left = join_by_code(admin, "left@example.com")
        stays = join_by_invite(admin, "stays@example.com", tier=2)
        join_by_code(admin, "plain@example.com", tier=None)
        orgs.deactivate_membership(left, by=admin)
        other, other_admin = org_with_admin("Globex")
        elsewhere = join_by_code(other_admin, "elsewhere@example.com", tier=1)
        assert orgs.joined_without_licence(enterprise) == {stays.pk: 2}
        assert orgs.joined_without_licence(other) == {elsewhere.pk: 1}

    def test_erasing_them_ends_it_too(self, empty):
        enterprise, admin = empty
        member = join_by_code(admin)
        erasure.erase_account(member.account)
        assert orgs.joined_without_licence(enterprise) == {}


# --- a member who comes back ----------------------------------------------------------


@pytest.mark.django_db
class TestAMemberWhoComesBack:
    def back_with_an_invite(self, admin, member, tier=2):
        orgs.deactivate_membership(member, by=admin)
        invite, _sent = orgs.invite_by_email(admin, member.account.email, tier=tier)
        return orgs.accept_invite(invite.token, member.account)

    def test_keeps_the_unused_licence_they_had_and_gets_no_second(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, CAROL)
        kept = licences.assign_seat(admin, member, 2)
        back = self.back_with_an_invite(admin, member)
        assert back.pk == member.pk and back.is_active
        assert licences_of(back) == [kept]
        assert stock_line(enterprise, 2)["given"] == 1
        assert orgs.joined_without_licence(enterprise) == {}

    def test_gets_one_if_they_have_none_in_hand(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, CAROL)
        used = licences.assign_seat(admin, member, 2)
        take_survey(used, submitted=True)
        back = self.back_with_an_invite(admin, member)
        assert len(licences_of(back)) == 2
        assert stock_line(enterprise, 2) == {"tier": 2, "bought": 2, "given": 2, "left": 0}


# --- the service by itself -------------------------------------------------------------


@pytest.mark.django_db
class TestGivingOnJoiningDirectly:
    def test_it_returns_the_licence_or_none(self, acme):
        enterprise = acme[0]
        first, second, third = (
            new_member(enterprise, f"person{number}@example.com") for number in range(3)
        )
        assert licences.give_seat_on_joining(first, 2).membership == first
        assert licences.give_seat_on_joining(first, 2) is None  # one in hand already
        assert licences.give_seat_on_joining(second, 2).tier == 2
        assert licences.give_seat_on_joining(third, 2) is None  # none left
        assert stock_line(enterprise, 2)["given"] == 2

    def test_a_member_who_did_not_come_in_by_invite_or_code_has_no_grantor(self, acme):
        member = new_member(acme[0], CAROL)
        assert licences.give_seat_on_joining(member, 2).granted_by is None

    def test_a_deactivated_member_gets_none(self, acme):
        member = new_member(acme[0], CAROL, active=False)
        assert licences.give_seat_on_joining(member, 2) is None
        assert licences_of(member) == []

    @pytest.mark.parametrize("tier", [0, 4, "2", 2.0, True, None])
    def test_anything_but_a_tier_is_an_error(self, acme, tier):
        member = new_member(acme[0], CAROL)
        with pytest.raises(licences.Refused):
            licences.give_seat_on_joining(member, tier)
        assert licences_of(member) == []

    def test_called_by_itself_it_still_locks_the_organization_first(self, acme):
        """A join already holds the organization's lock; another caller would not."""
        member = new_member(acme[0], CAROL)
        with CaptureQueriesContext(connection) as queries:
            licences.give_seat_on_joining(member, 2)
        assert lock_order(queries) == [ORGANIZATION, MEMBERSHIP, LICENCE]

    def test_the_locks_are_taken_in_the_usual_order(self, acme):
        """The organization, then the membership, then the licences: the same as assign_seat."""
        _, admin = acme
        code = orgs.create_code(admin, 5, tier=2)
        account = verified_account(CAROL)
        with CaptureQueriesContext(connection) as queries:
            orgs.redeem_code(code.code, account)
        order = lock_order(queries)
        assert order[0] == ORGANIZATION
        assert order.index(ORGANIZATION) < order.index(MEMBERSHIP) < order.index(LICENCE)


@pytest.mark.django_db(transaction=True)
def test_two_people_joining_at_once_cannot_both_get_the_last_licence():
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 1)
    code = orgs.create_code(admin, 5, tier=2)
    first, second = verified_account("first@example.com"), verified_account("second@example.com")
    results = run_together(
        lambda: orgs.redeem_code(code.code, first),
        lambda: orgs.redeem_code(code.code, second),
    )
    assert all(isinstance(result, Membership) for result in results), results
    assert Membership.objects.filter(enterprise=enterprise).count() == 3  # both joined
    given = Entitlement.objects.filter(membership__enterprise=enterprise, source="seat")
    assert given.count() == 1
    assert stock_line(enterprise, 2) == {"tier": 2, "bought": 1, "given": 1, "left": 0}
    assert len(orgs.joined_without_licence(enterprise)) == 1


# --- a join never fails because of the stock ------------------------------------------


@pytest.mark.django_db
class TestAJoinNeverFailsBecauseOfALicence:
    def test_if_giving_the_licence_blows_up_the_person_still_joins(self, acme, monkeypatch, caplog):
        enterprise, admin = acme

        def broken(membership, tier):
            raise RuntimeError("the stock is on fire")

        monkeypatch.setattr(licences, "give_seat_on_joining", broken)
        with caplog.at_level(logging.ERROR, logger="apps.enterprises.services"):
            by_code = join_by_code(admin)
            by_invite = join_by_invite(admin, "dan@example.com")
        for member in (by_code, by_invite):
            assert fresh(member).is_active and licences_of(member) == []
        assert JoinCode.objects.get().uses == 1
        assert Invite.objects.get().accepted_at is not None
        # Staff are told, and the line names nobody.
        said = [record.getMessage() for record in caplog.records]
        assert len(said) == 2 and all("member_joined" in line for line in said)
        for line in said:
            assert "@" not in line and "example.com" not in line
        # The admin's page still says they joined without one.
        assert orgs.joined_without_licence(enterprise) == {by_code.pk: 2, by_invite.pk: 2}

    def test_what_a_failing_listener_wrote_is_undone_and_the_join_is_kept(self, acme):
        """Even a database error: without the savepoint the whole join would be lost."""
        admin = acme[1]

        def half_done(sender, membership, tier, **kwargs):
            Entitlement.objects.create(membership=membership, tier=1, source="seat")
            # Breaks a database rule (the tier must be 1 to 3).
            Entitlement.objects.create(membership=membership, tier=9, source="seat")

        orgs.member_joined.connect(half_done)
        try:
            member = join_by_code(admin, tier=None)
        finally:
            orgs.member_joined.disconnect(half_done)
        assert fresh(member).is_active
        assert licences_of(member) == []  # the first, valid row went with the failure
        assert JoinCode.objects.get().uses == 1

    def test_every_join_is_announced_with_the_membership_and_the_tier(self, acme):
        _, admin = acme
        heard = []

        def listen(sender, membership, tier, **kwargs):
            heard.append((sender, membership.pk, tier))

        orgs.member_joined.connect(listen)
        try:
            one = join_by_code(admin, "one@example.com", tier=None)
            two = join_by_invite(admin, "two@example.com", tier=2)
        finally:
            orgs.member_joined.disconnect(listen)
        assert heard == [(Membership, one.pk, None), (Membership, two.pk, 2)]

    def test_a_refused_join_announces_nothing_and_gives_nothing(self, acme):
        _, admin = acme
        code = orgs.create_code(admin, 1, tier=2)
        orgs.redeem_code(code.code, verified_account("one@example.com"))
        late = verified_account("late@example.com")
        with pytest.raises(orgs.Refused):
            orgs.redeem_code(code.code, late)  # used up
        assert Entitlement.objects.count() == 1 and not late.memberships.exists()


# --- the forms -----------------------------------------------------------------------


@pytest.mark.django_db
class TestTheFormsAskForATier:
    def test_both_forms_offer_no_licence_first_and_the_three_tiers(self, client, admin):
        for address in (CODES, INVITES):
            text = html(client, address)
            assert 'name="tier"' in text and NO_LICENCE in text
            for tier in (1, 2, 3):
                assert f'<option value="{tier}">Tier {tier} licence</option>' in text
            assert "If none is left then, they still join, without a licence." in text

    def test_a_code_made_with_a_tier_says_what_it_gives(self, client, admin):
        landed, text = after(client, CODES, {"max_uses": "5", "days": "30", "tier": "2"})
        assert landed == CODES and JoinCode.objects.get().tier == 2
        assert client.get(CODES).context["rows"][0]["tier"] == 2
        assert "Gives a Tier 2 licence" in text

    def test_a_code_made_without_one_gives_none(self, client, admin):
        for data in ({"max_uses": "5", "days": "30"}, {"max_uses": "5", "days": "30", "tier": ""}):
            _, text = after(client, CODES, data)
            assert "Gives a" not in text
        assert [code.tier for code in JoinCode.objects.all()] == [None, None]

    def test_an_invite_sent_with_a_tier_says_what_comes_with_it(self, client, admin):
        landed, text = after(client, INVITES, {"email": CAROL, "tier": "3"})
        assert landed == INVITES and Invite.objects.get().tier == 3
        assert client.get(INVITES).context["rows"][0]["tier"] == 3
        assert "Comes with a Tier 3 licence" in text

    def test_an_invite_sent_without_one_comes_with_none(self, client, admin):
        _, text = after(client, INVITES, {"email": CAROL})
        assert Invite.objects.get().tier is None and "Comes with a" not in text

    @pytest.mark.parametrize("typed", ["0", "4", "2.0", "two", "True"])
    def test_anything_but_a_tier_is_asked_for_again(self, client, admin, typed):
        for address, data in (
            (CODES, {"max_uses": "5", "days": "30"}),
            (INVITES, {"email": CAROL}),
        ):
            page = client.post(address, {**data, "tier": typed})
            assert page.status_code == 200
            assert "Choose a tier from the list, or no licence." in page.content.decode()
        assert not JoinCode.objects.exists() and not Invite.objects.exists()

    def test_a_tier_can_be_chosen_while_the_stock_has_none(self, client, admin):
        """The stock is checked when someone joins, not when the code is made."""
        _, text = after(client, CODES, {"max_uses": "5", "days": "30", "tier": "1"})
        assert JoinCode.objects.get().tier == 1 and "Gives a Tier 1 licence" in text


# --- what the person who joins sees ---------------------------------------------------


@pytest.mark.django_db
class TestWhatTheJoinerSees:
    @pytest.fixture
    def carol(self, client):
        account = verified_account(CAROL)
        client.force_login(account)
        return account

    def test_the_page_before_joining_does_not_promise_a_licence(self, client, acme, carol):
        code = orgs.create_code(acme[1], 5, tier=2)
        text = " ".join(client.post("/join/code/", {"code": code.code}).content.decode().split())
        assert "To take the survey for Acme you also need a licence from it." in text
        assert "It may give you one as you join, or later." in text
        assert "Tier" not in text  # nothing about the organization but its name

    def test_joining_with_a_licence_says_so(self, client, acme, carol):
        code = orgs.create_code(acme[1], 5, tier=2)
        landed, text = after(client, "/join/code/", {"code": code.code, "confirm": "yes"})
        assert landed == ACME
        assert "You have joined Acme. You have a licence to take the survey for it." in text

    def test_by_invite_too(self, client, acme, carol):
        invite, _sent = orgs.invite_by_email(acme[1], CAROL, tier=2)
        _, text = after(client, f"/join/invite/{invite.token}/")
        assert "You have joined Acme. You have a licence to take the survey for it." in text

    def test_joining_without_one_does_not(self, client, acme, carol):
        orgs.set_seat_pool(acme[0], 2, 0)
        code = orgs.create_code(acme[1], 5, tier=2)
        _, text = after(client, "/join/code/", {"code": code.code, "confirm": "yes"})
        assert "You have joined Acme." in text and "You have a licence" not in text


# --- the warning on the admin's pages -------------------------------------------------


@pytest.mark.django_db
class TestTheWarning:
    @pytest.fixture
    def empty(self, acme):
        orgs.set_seat_pool(acme[0], 2, 0)
        return acme

    def test_nothing_is_said_when_everyone_got_theirs(self, client, admin):
        join_by_code(admin)
        for address in (ACME, LICENCES):
            page = client.get(address)
            assert page.context["without_licence"] == 0
            assert "data-without-licence" not in page.content.decode()

    def test_it_counts_the_people_who_joined_without_one(self, client, empty, admin):
        join_by_code(admin, "one@example.com")
        for address in (ACME, LICENCES):
            assert client.get(address).context["without_licence"] == 1
            assert "1 member joined with an invite or a join code" in html(client, address)
        join_by_invite(admin, "two@example.com")
        for address in (ACME, LICENCES):
            assert client.get(address).context["without_licence"] == 2
            assert "2 members joined with an invite or a join code" in html(client, address)
        assert "You can give them one on the Licences page." in html(client, ACME)

    def test_the_licences_page_marks_who(self, client, empty, admin):
        member = join_by_code(admin)
        accounts.set_full_name(member.account, "Carol Example")
        rows = {row["id"]: row for row in client.get(LICENCES).context["rows"]}
        assert rows[member.pk]["promised"] == 2 and rows[admin.pk]["promised"] is None
        text = html(client, LICENCES)
        assert "for a Tier 2 licence, but none was left." in text
        assert text.count("data-promised") == 1

    def test_giving_them_one_on_the_page_clears_it(self, client, empty, admin):
        member = join_by_code(admin)
        orgs.set_seat_pool(empty[0], 2, 1)
        _, text = after(client, f"{LICENCES}members/{member.pk}/give/", {"tier": "2"})
        assert "data-without-licence" not in text and "data-promised" not in text
        assert client.get(ACME).context["without_licence"] == 0

    def test_a_member_who_is_not_an_admin_is_told_nothing(self, client, empty):
        member = join_by_code(empty[1])
        client.force_login(member.account)
        page = client.get(ACME)
        assert page.status_code == 200 and "without_licence" not in page.context
        assert "data-without-licence" not in page.content.decode()
