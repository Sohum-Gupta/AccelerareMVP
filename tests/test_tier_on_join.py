"""
A tier on an invite or a join code: the licence it promises is set aside.

The rules (the founder's, 2026-11-13; Milestone 4, second part). The admin may
choose a tier when sending an invite or making a join code. One licence of that
tier is then set aside out of the organization's stock for the invite, or one
for each person the code allows, and making it is refused when the stock cannot
cover it. Whoever joins is given the licence that was set aside for them. A
licence set aside comes back when the invite is withdrawn or expires, or the
code is switched off or expires. The page read before joining says when a
licence comes with the invite or code.

How it is built. Nothing is stored for "set aside": it is counted from the
invites and codes themselves (`seats_set_aside`). The organizations app may not
import the licences app, so it announces every join with a signal
(`member_joined`) and the licences app gives the licence. The join and the
licence happen together or not at all.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts import erasure
from apps.enterprises import services as orgs
from apps.enterprises.models import Invite, JoinCode, Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement

from .orgs import add_member, new_member, org_with_admin, run_together
from .test_enterprise_services import expire, refusal
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


def line(enterprise, tier=2):
    """The stock of one tier as (bought, given, set aside, left)."""
    row = stock_line(enterprise, tier)
    return row["bought"], row["given"], row["set_aside"], row["left"]


def join_by_code(admin, email=CAROL, tier=2, max_uses=1):
    """Someone new joins with a fresh code that carries this tier. Returns their membership."""
    code = orgs.create_code(admin, max_uses, tier=tier)
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


# --- making an invite or a code sets licences aside -----------------------------------


@pytest.mark.django_db
class TestSettingAside:
    def test_an_invite_with_a_tier_sets_one_aside(self, acme):
        enterprise, admin = acme
        orgs.invite_by_email(admin, CAROL, tier=2)
        assert line(enterprise) == (2, 0, 1, 1)
        assert orgs.seats_set_aside(enterprise) == {1: 0, 2: 1, 3: 0}
        assert events() == []  # nothing has been given yet

    def test_a_code_with_a_tier_sets_one_aside_for_each_person_it_allows(self, acme):
        enterprise, admin = acme
        orgs.create_code(admin, 2, tier=2)
        assert line(enterprise) == (2, 0, 2, 0)

    def test_an_invite_is_refused_when_none_is_left(self, acme):
        enterprise, admin = acme
        orgs.create_code(admin, 2, tier=2)
        said = refusal(lambda: orgs.invite_by_email(admin, CAROL, tier=2))
        assert said.startswith("Your stock has no Tier 2 licences left")
        assert not Invite.objects.exists()  # so it used no place either
        assert orgs.places_left(enterprise) == 27

    def test_a_code_is_refused_when_the_stock_cannot_cover_everyone_it_allows(self, acme):
        _, admin = acme
        said = refusal(lambda: orgs.create_code(admin, 3, tier=2))
        assert "to each of 3 people, but your stock has only 2 left" in said
        orgs.invite_by_email(admin, CAROL, tier=2)
        orgs.invite_by_email(admin, "dan@example.com", tier=2)
        said = refusal(lambda: orgs.create_code(admin, 1, tier=2))
        assert "to each of 1 person, but your stock has none left" in said
        assert not JoinCode.objects.exists()

    def test_a_stock_of_another_tier_is_not_used_instead(self, acme):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 3, 5)
        refusal(lambda: orgs.invite_by_email(admin, CAROL, tier=1))
        refusal(lambda: orgs.create_code(admin, 1, tier=1))
        assert orgs.seats_set_aside(enterprise) == {1: 0, 2: 0, 3: 0}

    def test_without_a_tier_nothing_is_set_aside_and_the_stock_is_not_asked(self, acme):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 2, 0)
        orgs.invite_by_email(admin, CAROL)
        orgs.create_code(admin, 50)
        assert orgs.seats_set_aside(enterprise) == {1: 0, 2: 0, 3: 0}

    def test_a_licence_set_aside_cannot_be_given_by_hand_or_moved_into(self, acme):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 3, 1)
        member = new_member(enterprise, "bob@example.com")
        orgs.create_code(admin, 2, tier=2)
        assert refusal(lambda: licences.assign_seat(admin, member, 2)) == (
            "There are no Tier 2 licences left to give."
        )
        tier_three = licences.assign_seat(admin, member, 3)
        refusal(lambda: licences.change_seat_tier(admin, tier_three, 2))
        assert line(enterprise) == (2, 0, 2, 0)

    def test_a_licence_staff_granted_takes_nothing_from_what_can_be_set_aside(self, acme):
        enterprise, admin = acme
        for number in range(2):
            grant(new_member(enterprise, f"gift{number}@example.com"), 2)
        orgs.create_code(admin, 2, tier=2)
        assert line(enterprise) == (2, 0, 2, 0)

    def test_another_organizations_invites_and_codes_do_not_count(self, acme):
        enterprise, _ = acme
        other, other_admin = org_with_admin("Globex")
        orgs.set_seat_pool(other, 2, 5)
        orgs.create_code(other_admin, 3, tier=2)
        orgs.invite_by_email(other_admin, CAROL, tier=2)
        assert line(enterprise) == (2, 0, 0, 2) and line(other) == (5, 0, 4, 1)

    def test_only_an_active_admin_can_and_the_organization_is_locked_first(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, "bob@example.com")
        assert refusal(lambda: orgs.create_code(member, 1, tier=2)) == (
            "Only an admin of this organization can do that."
        )
        with CaptureQueriesContext(connection) as queries:
            orgs.create_code(admin, 1, tier=2)
        assert lock_order(queries)[0] == ORGANIZATION


@pytest.mark.django_db(transaction=True)
def test_two_admins_promising_the_last_licence_at_the_same_moment_promise_exactly_one():
    enterprise, first = org_with_admin("Acme")
    second = add_member(enterprise, verified_account("second@example.com"), role="admin")
    orgs.set_seat_pool(enterprise, 2, 1)
    results = run_together(
        lambda: orgs.invite_by_email(first, "one@example.com", tier=2),
        lambda: orgs.create_code(second, 1, tier=2),
    )
    assert sum(isinstance(result, orgs.Refused) for result in results) == 1, results
    assert Invite.objects.count() + JoinCode.objects.count() == 1
    assert line(enterprise) == (1, 0, 1, 0)


# --- a licence set aside comes back ---------------------------------------------------


@pytest.mark.django_db
class TestItComesBack:
    def test_when_the_invite_is_withdrawn(self, acme):
        enterprise, admin = acme
        invite, _sent = orgs.invite_by_email(admin, CAROL, tier=2)
        orgs.revoke_invite(invite, by=admin)
        assert line(enterprise) == (2, 0, 0, 2)

    def test_when_the_invite_expires(self, acme):
        enterprise, admin = acme
        invite, _sent = orgs.invite_by_email(admin, CAROL, tier=2)
        expire(invite)
        assert line(enterprise) == (2, 0, 0, 2)

    def test_when_the_person_it_was_sent_to_is_erased(self, acme):
        enterprise, admin = acme
        carol = verified_account(CAROL)
        orgs.invite_by_email(admin, CAROL, tier=2)
        assert line(enterprise) == (2, 0, 1, 1)
        erasure.erase_account(carol)
        assert Invite.objects.get().email == ""
        assert line(enterprise) == (2, 0, 0, 2)

    def test_when_the_code_is_switched_off_or_expires(self, acme):
        enterprise, admin = acme
        first = orgs.create_code(admin, 1, tier=2)
        second = orgs.create_code(admin, 1, tier=2)
        assert line(enterprise) == (2, 0, 2, 0)
        orgs.revoke_code(first, by=admin)
        assert line(enterprise) == (2, 0, 1, 1)
        expire(second)
        assert line(enterprise) == (2, 0, 0, 2)

    def test_only_the_uses_nobody_took_come_back(self, acme):
        enterprise, admin = acme
        code = orgs.create_code(admin, 2, tier=2)
        orgs.redeem_code(code.code, verified_account(CAROL))
        assert line(enterprise) == (2, 1, 1, 0)
        orgs.revoke_code(code, by=admin)
        assert line(enterprise) == (2, 1, 0, 1)  # the licence already given stays given

    def test_what_came_back_can_be_promised_or_given_again(self, acme):
        enterprise, admin = acme
        code = orgs.create_code(admin, 2, tier=2)
        orgs.revoke_code(code, by=admin)
        orgs.invite_by_email(admin, CAROL, tier=2)
        licences.assign_seat(admin, new_member(enterprise, "bob@example.com"), 2)
        assert line(enterprise) == (2, 1, 1, 0)


# --- joining brings the licence -------------------------------------------------------


@pytest.mark.django_db
class TestJoiningBringsTheLicence:
    def test_a_code_with_a_tier_gives_whoever_joins_the_licence_set_aside(self, acme):
        enterprise, admin = acme
        code = orgs.create_code(admin, 1, tier=2)
        before = line(enterprise)
        member = orgs.redeem_code(code.code, verified_account(CAROL))
        (licence,) = licences_of(member)
        assert (licence.tier, licence.source, licence.person) == (2, "seat", None)
        assert licence.is_active and licence.granted_by == admin.account  # who made the code
        assert before == (2, 0, 1, 1) and line(enterprise) == (2, 1, 0, 1)  # "left" did not move
        assert events() == [("licence_granted", 2, "seat")]
        assert licences.has_survey_access(member.account, member)

    def test_an_invite_with_a_tier_does_the_same(self, acme):
        enterprise, admin = acme
        member = join_by_invite(admin)
        (licence,) = licences_of(member)
        assert (licence.tier, licence.source, licence.granted_by) == (2, "seat", admin.account)
        assert line(enterprise) == (2, 1, 0, 1)
        assert events() == [("licence_granted", 2, "seat")]

    def test_without_a_tier_joining_gives_no_licence(self, acme):
        _, admin = acme
        for member in (
            join_by_code(admin, tier=None),
            join_by_invite(admin, "dan@example.com", tier=None),
        ):
            assert licences_of(member) == []
        assert events() == []

    def test_everyone_the_code_allows_gets_one(self, acme):
        enterprise, admin = acme
        code = orgs.create_code(admin, 2, tier=2)
        people = [
            orgs.redeem_code(code.code, verified_account(f"person{number}@example.com"))
            for number in range(2)
        ]
        assert [len(licences_of(person)) for person in people] == [1, 1]
        assert line(enterprise) == (2, 2, 0, 0)
        late = verified_account("late@example.com")
        refusal(lambda: orgs.redeem_code(code.code, late))  # used up
        assert not late.memberships.exists()

    def test_the_licence_counts_against_the_tier_it_names(self, acme):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 3, 1)
        member = join_by_code(admin, tier=3)
        assert [licence.tier for licence in licences_of(member)] == [3]
        assert line(enterprise, 3) == (1, 1, 0, 0) and line(enterprise, 2) == (2, 0, 0, 2)

    def test_a_promise_is_kept_even_if_staff_lower_the_stock_meanwhile(self, acme):
        """Nobody loses a promise: the page then shows more given than bought."""
        enterprise, admin = acme
        code = orgs.create_code(admin, 1, tier=2)
        orgs.set_seat_pool(enterprise, 2, 0)
        assert line(enterprise) == (0, 0, 1, 0)
        member = orgs.redeem_code(code.code, verified_account(CAROL))
        assert len(licences_of(member)) == 1
        assert line(enterprise) == (0, 1, 0, 0)
        refusal(lambda: orgs.invite_by_email(admin, "dan@example.com", tier=2))


# --- a member who comes back ----------------------------------------------------------


@pytest.mark.django_db
class TestAMemberWhoComesBack:
    def back_with_an_invite(self, admin, member, tier=2):
        orgs.deactivate_membership(member, by=admin)
        invite, _sent = orgs.invite_by_email(admin, member.account.email, tier=tier)
        return orgs.accept_invite(invite.token, member.account)

    def test_keeps_the_unused_licence_they_had_and_the_one_set_aside_returns(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, CAROL)
        kept = licences.assign_seat(admin, member, 2)
        back = self.back_with_an_invite(admin, member)
        assert back.pk == member.pk and back.is_active
        assert licences_of(back) == [kept]
        assert line(enterprise) == (2, 1, 0, 1)

    def test_gets_the_one_set_aside_if_they_have_none_in_hand(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, CAROL)
        used = licences.assign_seat(admin, member, 2)
        take_survey(used, submitted=True)
        back = self.back_with_an_invite(admin, member)
        assert len(licences_of(back)) == 2
        assert line(enterprise) == (2, 2, 0, 0)


# --- the service by itself -------------------------------------------------------------


@pytest.mark.django_db
class TestGivingOnJoiningDirectly:
    def test_it_returns_the_licence_or_none_for_someone_who_holds_one(self, acme):
        enterprise = acme[0]
        first, second = (new_member(enterprise, f"person{n}@example.com") for n in range(2))
        assert licences.give_seat_on_joining(first, 2).membership == first
        assert licences.give_seat_on_joining(first, 2) is None  # one in hand already
        assert licences.give_seat_on_joining(second, 2).tier == 2
        assert line(enterprise)[1] == 2

    def test_it_does_not_ask_the_stock(self, acme):
        """The licence was set aside when the invite or code was made; only a join calls this."""
        enterprise = acme[0]
        orgs.set_seat_pool(enterprise, 2, 0)
        member = new_member(enterprise, CAROL)
        assert licences.give_seat_on_joining(member, 2).tier == 2

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
        code = orgs.create_code(admin, 2, tier=2)
        account = verified_account(CAROL)
        with CaptureQueriesContext(connection) as queries:
            orgs.redeem_code(code.code, account)
        order = lock_order(queries)
        assert order[0] == ORGANIZATION
        assert order.index(ORGANIZATION) < order.index(MEMBERSHIP) < order.index(LICENCE)


@pytest.mark.django_db(transaction=True)
def test_two_people_joining_at_once_each_get_the_licence_set_aside_for_them():
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 2)
    code = orgs.create_code(admin, 2, tier=2)
    first, second = verified_account("first@example.com"), verified_account("second@example.com")
    results = run_together(
        lambda: orgs.redeem_code(code.code, first),
        lambda: orgs.redeem_code(code.code, second),
    )
    assert all(isinstance(result, Membership) for result in results), results
    given = Entitlement.objects.filter(membership__enterprise=enterprise, source="seat")
    assert given.count() == 2
    assert {licence.membership.account_id for licence in given} == {first.pk, second.pk}
    assert line(enterprise) == (2, 2, 0, 0)


# --- the join and the licence happen together or not at all ---------------------------


@pytest.mark.django_db
class TestTheJoinAndTheLicenceHappenTogether:
    def test_if_giving_the_licence_blows_up_the_join_is_undone(self, acme, monkeypatch):
        """Nobody is let in without the licence the page promised; they can try again."""
        enterprise, admin = acme
        code = orgs.create_code(admin, 1, tier=2)
        invite, _sent = orgs.invite_by_email(admin, "dan@example.com", tier=2)
        carol, dan = verified_account(CAROL), verified_account("dan@example.com")

        def broken(membership, tier):
            raise RuntimeError("something nobody planned for")

        monkeypatch.setattr(licences, "give_seat_on_joining", broken)
        with pytest.raises(RuntimeError):
            orgs.redeem_code(code.code, carol)
        with pytest.raises(RuntimeError):
            orgs.accept_invite(invite.token, dan)
        assert not carol.memberships.exists() and not dan.memberships.exists()
        assert fresh(code).uses == 0 and fresh(invite).accepted_at is None
        assert line(enterprise) == (2, 0, 2, 0)  # both promises are still waiting

        monkeypatch.undo()
        assert len(licences_of(orgs.redeem_code(code.code, carol))) == 1
        assert len(licences_of(orgs.accept_invite(invite.token, dan))) == 1

    def test_what_a_failing_listener_wrote_goes_with_the_join(self, acme):
        admin = acme[1]
        code = orgs.create_code(admin, 1)
        carol = verified_account(CAROL)

        def half_done(sender, membership, tier, **kwargs):
            Entitlement.objects.create(membership=membership, tier=1, source="seat")
            raise RuntimeError("after writing a row")

        orgs.member_joined.connect(half_done)
        try:
            with pytest.raises(RuntimeError):
                orgs.redeem_code(code.code, carol)
        finally:
            orgs.member_joined.disconnect(half_done)
        assert not Entitlement.objects.exists() and not carol.memberships.exists()
        assert fresh(code).uses == 0

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
    def test_both_forms_offer_no_licence_first_and_say_how_many_of_each_tier_are_left(
        self, client, admin
    ):
        for address in (CODES, INVITES):
            text = html(client, address)
            assert 'name="tier"' in text and NO_LICENCE in text
            assert '<option value="1">Tier 1 licence (none left)</option>' in text
            assert '<option value="2">Tier 2 licence (2 left)</option>' in text
            assert '<option value="3">Tier 3 licence (none left)</option>' in text
            assert "set aside from your stock" in text

    def test_the_count_in_the_list_goes_down_as_licences_are_set_aside(self, client, admin):
        orgs.invite_by_email(admin, CAROL, tier=2)
        for address in (CODES, INVITES):
            assert '<option value="2">Tier 2 licence (1 left)</option>' in html(client, address)

    def test_a_code_made_with_a_tier_says_what_it_gives(self, client, admin):
        landed, text = after(client, CODES, {"max_uses": "2", "days": "30", "tier": "2"})
        assert landed == CODES and JoinCode.objects.get().tier == 2
        assert client.get(CODES).context["rows"][0]["tier"] == 2
        assert "Gives a Tier 2 licence" in text

    def test_a_code_for_more_people_than_the_stock_covers_is_refused_on_the_page(
        self, client, admin
    ):
        page = client.post(CODES, {"max_uses": "5", "days": "30", "tier": "2"})
        text = " ".join(page.content.decode().split())
        assert page.status_code == 200 and not JoinCode.objects.exists()
        assert "to each of 5 people, but your stock has only 2 left" in text
        assert 'value="5"' in text  # what they typed is kept

    def test_a_code_made_without_one_gives_none(self, client, admin):
        for data in ({"max_uses": "5", "days": "30"}, {"max_uses": "5", "days": "30", "tier": ""}):
            _, text = after(client, CODES, data)
            assert "Gives a" not in text
        assert [code.tier for code in JoinCode.objects.all()] == [None, None]

    def test_an_invite_sent_with_a_tier_says_what_comes_with_it(self, client, admin):
        landed, text = after(client, INVITES, {"email": CAROL, "tier": "2"})
        assert landed == INVITES and Invite.objects.get().tier == 2
        assert client.get(INVITES).context["rows"][0]["tier"] == 2
        assert "Comes with a Tier 2 licence" in text

    def test_an_invite_for_a_tier_with_none_left_is_refused_on_the_page(self, client, admin):
        page = client.post(INVITES, {"email": CAROL, "tier": "3"})
        assert page.status_code == 200 and not Invite.objects.exists()
        assert "Your stock has no Tier 3 licences left" in page.content.decode()

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


# --- what the admin's pages say about the stock ----------------------------------------


@pytest.mark.django_db
class TestTheStockLines:
    def test_they_say_how_many_are_set_aside(self, client, admin):
        orgs.invite_by_email(admin, CAROL, tier=2)
        for address in (ACME, LICENCES):
            text = html(client, address)
            assert "1 of 2 Tier 2 licences left" in text
            assert "1 set aside for invites and join codes" in text

    def test_they_say_nothing_of_it_when_nothing_is(self, client, admin):
        for address in (ACME, LICENCES):
            assert "data-set-aside" not in html(client, address)

    def test_a_tier_wholly_set_aside_cannot_be_given_on_the_licences_page(self, client, admin):
        orgs.create_code(admin, 2, tier=2)
        page = client.get(LICENCES)
        assert page.context["give_tiers"] == []
        assert "0 of 2 Tier 2 licences left" in " ".join(page.content.decode().split())

    def test_there_is_no_joined_without_a_licence_warning_any_more(self, client, admin):
        join_by_code(admin)
        for address in (ACME, LICENCES):
            page = client.get(address)
            assert "without_licence" not in page.context
            assert "data-without-licence" not in page.content.decode()
        assert all("promised" not in row for row in client.get(LICENCES).context["rows"])


# --- what the person who joins sees ---------------------------------------------------


@pytest.mark.django_db
class TestWhatTheJoinerSees:
    @pytest.fixture
    def carol(self, client):
        account = verified_account(CAROL)
        client.force_login(account)
        return account

    def confirmation(self, client, address, data=None):
        page = client.post(address, data) if data else client.get(address)
        return " ".join(page.content.decode().split())

    def test_the_page_before_joining_says_a_code_comes_with_a_licence(self, client, acme, carol):
        code = orgs.create_code(acme[1], 2, tier=2)
        text = self.confirmation(client, "/join/code/", {"code": code.code})
        assert (
            "Joining makes you a member. "
            "This code comes with a licence to take the survey for Acme."
        ) in text
        assert "you also need a licence" not in text
        assert "Tier" not in text  # the level is not named
        assert not carol.memberships.exists()  # reading the page joins nothing

    def test_and_an_invite(self, client, acme, carol):
        invite, _sent = orgs.invite_by_email(acme[1], CAROL, tier=2)
        text = self.confirmation(client, f"/join/invite/{invite.token}/")
        assert "This invite comes with a licence to take the survey for Acme." in text
        assert "Tier" not in text

    def test_without_a_tier_it_says_a_licence_may_come_later(self, client, acme, carol):
        code = orgs.create_code(acme[1], 2)
        invite, _sent = orgs.invite_by_email(acme[1], CAROL)
        for text in (
            self.confirmation(client, "/join/code/", {"code": code.code}),
            self.confirmation(client, f"/join/invite/{invite.token}/"),
        ):
            assert (
                "Joining makes you a member. To take the survey for Acme you also need "
                "a licence from it, which it may give you later."
            ) in text
            assert "comes with a licence" not in text

    def test_joining_with_a_licence_says_so(self, client, acme, carol):
        code = orgs.create_code(acme[1], 2, tier=2)
        landed, text = after(client, "/join/code/", {"code": code.code, "confirm": "yes"})
        assert landed == ACME
        assert "You have joined Acme. You have a licence to take the survey for it." in text

    def test_by_invite_too(self, client, acme, carol):
        invite, _sent = orgs.invite_by_email(acme[1], CAROL, tier=2)
        _, text = after(client, f"/join/invite/{invite.token}/")
        assert "You have joined Acme. You have a licence to take the survey for it." in text

    def test_joining_without_one_does_not(self, client, acme, carol):
        code = orgs.create_code(acme[1], 2)
        _, text = after(client, "/join/code/", {"code": code.code, "confirm": "yes"})
        assert "You have joined Acme." in text and "You have a licence" not in text
