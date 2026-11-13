"""
Milestone 4, PR 2: an organization's admin gives licences out of its stock,
changes their tier and takes them back.

The rules (the founder's, 2026-11-13). A licence counts against the stock of
the tier it has now, from the moment it is given until it is taken back. It can
be taken back until its survey is submitted, and an unfinished attempt goes
with it; a submitted one is spent for good. Its tier can move up or down before
submission and only up afterwards. A licence staff granted by hand is outside
the stock and is not the organization's to change. A member holds at most one
licence they have not finished using.

Every rule is tested here, at the service, because the Licences page (PR 3)
only calls these. The tests that start threads prove the locks do their job.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts import erasure
from apps.enterprises import services as orgs
from apps.enterprises.models import Enterprise, Membership
from apps.entitlements import services
from apps.entitlements.models import Entitlement
from apps.funnel.models import FunnelEvent
from apps.responses import services as responses
from apps.responses.models import Response
from apps.survey.models import SurveyVersion
from apps.survey.services import current_version

from .orgs import new_member, org_with_admin, run_together
from .test_seat_pools import row, stock_licence, take_survey

Refused = services.Refused
NotFound = services.NotFound
NONE_LEFT = "There are no Tier 2 licences left to give."


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership), with 5 Tier 2 licences bought"""
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 5)
    return enterprise, admin


@pytest.fixture
def member(acme):
    return new_member(acme[0], "bob@example.com")


@pytest.fixture
def globex(db):
    """Another organization with its own stock: (the organization, its admin, a member)."""
    enterprise, admin = org_with_admin("Globex")
    orgs.set_seat_pool(enterprise, 2, 5)
    return enterprise, admin, new_member(enterprise, "gina@example.com")


def refusal(action, kind=Refused):
    """The plain-words message of the refusal that `action` raises."""
    with pytest.raises(kind) as caught:
        action()
    return str(caught.value)


def given(enterprise, tier=2):
    return orgs.seats_given(enterprise)[tier]


def events():
    """The funnel's licence and survey events, oldest first (sign-ups are left out)."""
    kinds = ("licence_granted", "licence_upgraded", "survey_started")
    rows = FunnelEvent.objects.filter(kind__in=kinds).order_by("id")
    return [(event.kind, event.tier, event.source) for event in rows]


def lock_order(queries):
    """The tables read with FOR UPDATE, in the order they were first locked."""
    order = []
    for query in queries:
        if "FOR UPDATE" in query["sql"]:
            table = query["sql"].split(" FROM ")[1].split()[0].strip('"')
            if table not in order:
                order.append(table)
    return order


ORGANIZATION, MEMBERSHIP, LICENCE, RESPONSE = (
    model._meta.db_table for model in (Enterprise, Membership, Entitlement, Response)
)


# --- giving ------------------------------------------------------------------------


@pytest.mark.django_db
class TestGiving:
    def test_an_admin_gives_a_member_a_licence_from_the_stock(self, acme, member):
        enterprise, admin = acme
        licence = services.assign_seat(admin, member, 2)
        assert (licence.membership, licence.person, licence.tier) == (member, None, 2)
        assert licence.source == "seat" and licence.granted_by == admin.account
        assert licence.is_active
        assert row(enterprise, 2) == {"tier": 2, "bought": 5, "given": 1, "set_aside": 0, "left": 4}
        assert events() == [("licence_granted", 2, "seat")]

    def test_the_member_can_then_take_the_survey_for_the_organization(self, acme, member):
        licence = services.assign_seat(acme[1], member, 2)
        assert services.has_survey_access(member.account, member)
        assert not services.has_survey_access(member.account)  # not personally
        response = responses.start_response(member.account, member)
        assert response.entitlement == licence and response.membership == member
        assert events()[-1] == ("survey_started", 2, "seat")

    def test_an_admin_can_give_one_to_themselves(self, acme):
        enterprise, admin = acme
        licence = services.assign_seat(admin, admin, 2)
        assert licence.membership == admin and given(enterprise) == 1

    def test_a_stock_of_two_refuses_the_third(self, acme, member):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 2, 2)
        services.assign_seat(admin, admin, 2)
        services.assign_seat(admin, member, 2)
        carol = new_member(enterprise, "carol@example.com")
        assert refusal(lambda: services.assign_seat(admin, carol, 2)) == NONE_LEFT
        assert Entitlement.objects.count() == 2 and not carol.entitlements.exists()
        assert len(events()) == 2

    def test_each_tier_has_its_own_stock(self, acme, member):
        enterprise, admin = acme
        message = refusal(lambda: services.assign_seat(admin, member, 3))
        assert message == "There are no Tier 3 licences left to give."
        orgs.set_seat_pool(enterprise, 3, 1)
        assert services.assign_seat(admin, member, 3).tier == 3
        assert orgs.seats_given(enterprise) == {1: 0, 2: 0, 3: 1}

    def test_licences_staff_granted_by_hand_use_none_of_the_stock(self, acme, member):
        enterprise, admin = acme
        orgs.set_seat_pool(enterprise, 2, 1)
        services.grant_for_membership(admin, 2, "manual", None)
        assert services.assign_seat(admin, member, 2).pk
        assert row(enterprise, 2)["left"] == 0

    def test_a_stock_lowered_below_what_is_given_blocks_new_ones(self, acme, member):
        enterprise, admin = acme
        services.assign_seat(admin, admin, 2)
        services.assign_seat(admin, member, 2)
        orgs.set_seat_pool(enterprise, 2, 1)
        carol = new_member(enterprise, "carol@example.com")
        assert refusal(lambda: services.assign_seat(admin, carol, 2)) == NONE_LEFT
        assert given(enterprise) == 2  # and nobody lost theirs

    def test_a_member_with_an_unused_licence_is_not_given_a_second(self, acme, member):
        enterprise, admin = acme
        services.assign_seat(admin, member, 2)
        message = refusal(lambda: services.assign_seat(admin, member, 2))
        assert message == "They already have a licence they have not used."
        assert given(enterprise) == 1

    def test_an_unused_licence_granted_by_staff_also_stands_in_the_way(self, acme, member):
        services.grant_for_membership(member, 1, "manual", None)
        message = refusal(lambda: services.assign_seat(acme[1], member, 2))
        assert message == services.ALREADY_HAS_ONE and given(acme[0]) == 0

    def test_a_member_part_way_through_the_survey_is_not_given_a_second(self, acme, member):
        enterprise, admin = acme
        take_survey(services.assign_seat(admin, member, 2))
        message = refusal(lambda: services.assign_seat(admin, member, 2))
        assert message == "They have not finished the survey on the licence they already have."
        assert given(enterprise) == 1

    def test_after_submitting_they_can_be_given_another(self, acme, member):
        """A retake needs another licence; the spent one still counts."""
        enterprise, admin = acme
        take_survey(services.assign_seat(admin, member, 2), submitted=True)
        assert services.assign_seat(admin, member, 2).pk
        assert given(enterprise) == 2

    def test_a_personal_licence_does_not_stand_in_the_way(self, acme, member):
        services.grant_individual(member.account.person, 1, "manual", None)
        assert services.assign_seat(acme[1], member, 2).pk

    def test_a_deactivated_member_cannot_be_given_one(self, acme, member):
        enterprise, admin = acme
        orgs.deactivate_membership(member, by=admin)
        message = refusal(lambda: services.assign_seat(admin, member, 2))
        assert "has been deactivated" in message and given(enterprise) == 0

    @pytest.mark.parametrize("tier", [0, 4, -1, "2", 2.0, True, None])
    def test_a_bad_tier_is_refused(self, acme, member, tier):
        message = refusal(lambda: services.assign_seat(acme[1], member, tier))
        assert message == "The tier must be 1, 2 or 3."
        assert not Entitlement.objects.exists()

    def test_it_locks_the_organization_then_the_membership_then_the_licences(self, acme, member):
        with CaptureQueriesContext(connection) as captured:
            services.assign_seat(acme[1], member, 2)
        assert lock_order(captured.captured_queries) == [ORGANIZATION, MEMBERSHIP, LICENCE]


# --- who may give, take back and change --------------------------------------------


@pytest.mark.django_db
class TestOnlyTheOrganizationsOwnAdmin:
    """Each of the three is tried by someone who should not be able to do it."""

    def attempts(self, by, member, licence):
        return (
            lambda: services.assign_seat(by, member, 2),
            lambda: services.take_back_seat(by, licence),
            lambda: services.change_seat_tier(by, licence, 1),
        )

    def unchanged(self, enterprise, licence):
        licence.refresh_from_db()
        return licence.is_active and licence.tier == 2 and given(enterprise) == 1

    @pytest.fixture
    def carol(self, acme):
        """A second member, who holds no licence."""
        return new_member(acme[0], "carol@example.com")

    @pytest.fixture
    def licence(self, acme, member):
        orgs.set_seat_pool(acme[0], 1, 5)
        return services.assign_seat(acme[1], member, 2)

    def test_an_ordinary_member_cannot(self, acme, member, carol, licence):
        for attempt in self.attempts(member, carol, licence):
            assert refusal(attempt) == "Only an admin of this organization can do that."
        assert self.unchanged(acme[0], licence)

    def test_an_admin_demoted_since_the_page_loaded_cannot(self, acme, member, carol, licence):
        enterprise, admin = acme
        second = new_member(enterprise, "dave@example.com", role="admin")
        orgs.set_role(second, "member", by=admin)
        # `second` is the copy the page still holds, which says "admin".
        assert second.role == "admin"
        for attempt in self.attempts(second, carol, licence):
            assert "Only an admin" in refusal(attempt)
        assert self.unchanged(enterprise, licence)

    def test_a_deactivated_admin_cannot(self, acme, member, carol, licence):
        enterprise, admin = acme
        second = new_member(enterprise, "dave@example.com", role="admin")
        orgs.deactivate_membership(second, by=admin)
        for attempt in self.attempts(second, carol, licence):
            assert "Only an admin" in refusal(attempt)
        assert self.unchanged(enterprise, licence)

    def test_another_organizations_admin_finds_neither_the_member_nor_the_licence(
        self, acme, member, carol, licence, globex
    ):
        _, outsider, _ = globex
        give, take_back, change = self.attempts(outsider, carol, licence)
        assert refusal(give, NotFound) == "That member was not found."
        assert refusal(take_back, NotFound) == "That licence was not found."
        assert refusal(change, NotFound) == "That licence was not found."
        assert self.unchanged(acme[0], licence)
        assert given(globex[0]) == 0 and not carol.entitlements.exists()

    def test_an_admin_cannot_give_their_stock_to_another_organizations_member(self, acme, globex):
        _, _, gina = globex
        refusal(lambda: services.assign_seat(acme[1], gina, 2), NotFound)
        assert not Entitlement.objects.exists()

    def test_a_personal_licence_is_not_found(self, acme, member):
        personal = services.grant_individual(member.account.person, 2, "manual", None)
        refusal(lambda: services.take_back_seat(acme[1], personal), NotFound)
        refusal(lambda: services.change_seat_tier(acme[1], personal, 3), NotFound)
        personal.refresh_from_db()
        assert personal.is_active and personal.tier == 2

    def test_a_licence_that_does_not_exist_is_not_found(self, acme):
        ghost = Entitlement(pk=999_999)
        refusal(lambda: services.take_back_seat(acme[1], ghost), NotFound)
        refusal(lambda: services.change_seat_tier(acme[1], ghost, 3), NotFound)


# --- taking back -------------------------------------------------------------------


@pytest.mark.django_db
class TestTakingBack:
    def test_an_unused_licence_goes_back_to_the_stock_and_keeps_its_record(self, acme, member):
        enterprise, admin = acme
        licence = services.assign_seat(admin, member, 2)
        taken, draft_deleted = services.take_back_seat(admin, licence)
        assert taken.pk == licence.pk and not draft_deleted
        licence.refresh_from_db()
        assert licence.revoked_at is not None  # revoked, not deleted
        assert row(enterprise, 2) == {"tier": 2, "bought": 5, "given": 0, "set_aside": 0, "left": 5}
        assert not services.has_survey_access(member.account, member)

    def test_one_in_progress_goes_back_and_the_unfinished_attempt_is_deleted(self, acme, member):
        enterprise, admin = acme
        licence = services.assign_seat(admin, member, 2)
        responses.start_response(member.account, member)
        _, draft_deleted = services.take_back_seat(admin, licence)
        assert draft_deleted and not Response.objects.exists()
        assert given(enterprise) == 0
        # The member can be given a licence again and start afresh.
        again = services.assign_seat(admin, member, 2)
        assert responses.start_response(member.account, member).entitlement == again

    def test_a_submitted_one_cannot_be_taken_back(self, acme, member):
        enterprise, admin = acme
        licence = services.assign_seat(admin, member, 2)
        done = take_survey(licence, submitted=True)
        message = refusal(lambda: services.take_back_seat(admin, licence))
        assert (
            message == "The survey on this licence has been submitted, so it cannot be taken back."
        )
        licence.refresh_from_db()
        assert licence.is_active and given(enterprise) == 1
        assert Response.objects.get() == done

    def test_one_staff_granted_by_hand_is_not_the_admins_to_take_back(self, acme, member):
        licence = services.grant_for_membership(member, 2, "manual", None)
        message = refusal(lambda: services.take_back_seat(acme[1], licence))
        assert message == services.NOT_FROM_STOCK
        licence.refresh_from_db()
        assert licence.is_active

    def test_a_deactivated_members_unused_licence_can_be_taken_back(self, acme, member):
        enterprise, admin = acme
        licence = services.assign_seat(admin, member, 2)
        orgs.deactivate_membership(member, by=admin)
        assert given(enterprise) == 1  # it stayed with the membership
        services.take_back_seat(admin, licence)
        assert given(enterprise) == 0

    def test_taking_back_twice_is_refused_and_keeps_the_first_date(self, acme, member):
        admin = acme[1]
        licence = services.assign_seat(admin, member, 2)
        services.take_back_seat(admin, licence)
        licence.refresh_from_db()
        first = licence.revoked_at
        message = refusal(lambda: services.take_back_seat(admin, licence))
        assert message == "That licence has already been taken back."
        licence.refresh_from_db()
        assert licence.revoked_at == first

    def test_an_admin_can_take_back_their_own(self, acme):
        enterprise, admin = acme
        services.take_back_seat(admin, services.assign_seat(admin, admin, 2))
        assert given(enterprise) == 0

    def test_it_locks_in_order_down_to_the_response(self, acme, member):
        licence = services.assign_seat(acme[1], member, 2)
        take_survey(licence)
        with CaptureQueriesContext(connection) as captured:
            services.take_back_seat(acme[1], licence)
        assert lock_order(captured.captured_queries) == [
            ORGANIZATION,
            MEMBERSHIP,
            LICENCE,
            RESPONSE,
        ]


# --- changing the tier -------------------------------------------------------------


@pytest.mark.django_db
class TestChangingTheTier:
    @pytest.fixture
    def stocked(self, acme):
        """Acme with 5 of Tier 2 (from `acme`), 1 of Tier 1 and 1 of Tier 3."""
        orgs.set_seat_pool(acme[0], 1, 1)
        orgs.set_seat_pool(acme[0], 3, 1)
        return acme

    def test_up_before_submission_moves_one_between_two_stocks(self, stocked, member):
        enterprise, admin = stocked
        licence = services.assign_seat(admin, member, 2)
        changed = services.change_seat_tier(admin, licence, 3)
        licence.refresh_from_db()
        assert changed.pk == licence.pk and licence.tier == 3 and licence.source == "seat"
        assert orgs.seats_given(enterprise) == {1: 0, 2: 0, 3: 1}
        assert row(enterprise, 2)["left"] == 5 and row(enterprise, 3)["left"] == 0
        assert events() == [("licence_granted", 2, "seat"), ("licence_upgraded", 3, "seat")]

    def test_down_before_submission_works_too_and_is_not_an_upgrade(self, stocked, member):
        enterprise, admin = stocked
        licence = services.assign_seat(admin, member, 2)
        take_survey(licence)  # in progress is still "before submission"
        services.change_seat_tier(admin, licence, 1)
        assert orgs.seats_given(enterprise) == {1: 1, 2: 0, 3: 0}
        assert events() == [("licence_granted", 2, "seat")]
        assert Response.objects.filter(status="draft").count() == 1  # the attempt carries on

    def test_a_full_tier_refuses_and_nothing_changes(self, stocked, member):
        enterprise, admin = stocked
        services.assign_seat(admin, admin, 3)  # the only Tier 3
        licence = services.assign_seat(admin, member, 2)
        message = refusal(lambda: services.change_seat_tier(admin, licence, 3))
        assert message == "There are no Tier 3 licences left to give."
        licence.refresh_from_db()
        assert licence.tier == 2
        assert orgs.seats_given(enterprise) == {1: 0, 2: 1, 3: 1}

    def test_the_same_tier_changes_nothing_even_when_that_tier_is_full(self, stocked, member):
        enterprise, admin = stocked
        licence = services.assign_seat(admin, member, 3)
        assert row(enterprise, 3)["left"] == 0
        assert services.change_seat_tier(admin, licence, 3).tier == 3
        assert events() == [("licence_granted", 3, "seat")]

    def test_after_submission_it_cannot_go_down(self, stocked, member):
        enterprise, admin = stocked
        licence = services.assign_seat(admin, member, 2)
        take_survey(licence, submitted=True)
        message = refusal(lambda: services.change_seat_tier(admin, licence, 1))
        assert (
            message == "The survey on this licence has been submitted, so its tier can only go up."
        )
        licence.refresh_from_db()
        assert licence.tier == 2 and orgs.seats_given(enterprise) == {1: 0, 2: 1, 3: 0}

    def test_after_submission_it_can_go_up_if_the_new_tier_has_one_left(self, stocked, member):
        enterprise, admin = stocked
        licence = services.assign_seat(admin, member, 2)
        take_survey(licence, submitted=True)
        services.change_seat_tier(admin, licence, 3)
        licence.refresh_from_db()
        assert licence.tier == 3 and orgs.seats_given(enterprise) == {1: 0, 2: 0, 3: 1}
        assert events()[-1] == ("licence_upgraded", 3, "seat")
        # And the spent Tier 3 is spent: the next upgrade to it is refused.
        other = services.assign_seat(admin, admin, 2)
        refusal(lambda: services.change_seat_tier(admin, other, 3))

    def test_a_deactivated_members_licence_can_still_be_changed(self, stocked, member):
        enterprise, admin = stocked
        licence = services.assign_seat(admin, member, 2)
        orgs.deactivate_membership(member, by=admin)
        services.change_seat_tier(admin, licence, 1)
        assert orgs.seats_given(enterprise) == {1: 1, 2: 0, 3: 0}

    def test_one_staff_granted_by_hand_is_not_the_admins_to_change(self, stocked, member):
        licence = services.grant_for_membership(member, 2, "manual", None)
        message = refusal(lambda: services.change_seat_tier(stocked[1], licence, 3))
        assert message == services.NOT_FROM_STOCK
        licence.refresh_from_db()
        assert licence.tier == 2

    def test_one_that_was_taken_back_cannot_be_changed(self, stocked, member):
        admin = stocked[1]
        licence = services.assign_seat(admin, member, 2)
        services.take_back_seat(admin, licence)
        message = refusal(lambda: services.change_seat_tier(admin, licence, 3))
        assert message == "That licence has already been taken back."

    @pytest.mark.parametrize("tier", [0, 4, "3", 3.0, True, None])
    def test_a_bad_tier_is_refused(self, stocked, member, tier):
        licence = services.assign_seat(stocked[1], member, 2)
        message = refusal(lambda: services.change_seat_tier(stocked[1], licence, tier))
        assert message == "The tier must be 1, 2 or 3."
        licence.refresh_from_db()
        assert licence.tier == 2

    def test_it_locks_in_order_down_to_the_response(self, stocked, member):
        licence = services.assign_seat(stocked[1], member, 2)
        take_survey(licence)
        with CaptureQueriesContext(connection) as captured:
            services.change_seat_tier(stocked[1], licence, 3)
        assert lock_order(captured.captured_queries) == [
            ORGANIZATION,
            MEMBERSHIP,
            LICENCE,
            RESPONSE,
        ]


# --- staff and the stock -----------------------------------------------------------


@pytest.mark.django_db
class TestStaffAndTheStock:
    def test_staff_revoking_a_licence_from_the_stock_frees_it(self, acme, member):
        enterprise, admin = acme
        licence = services.assign_seat(admin, member, 2)
        services.revoke(licence)
        assert given(enterprise) == 0
        assert services.assign_seat(admin, member, 2).pk

    def test_a_licence_from_another_organizations_stock_never_counts_here(self, acme, globex):
        other, other_admin, gina = globex
        services.assign_seat(other_admin, gina, 2)
        assert given(acme[0]) == 0 and given(other) == 1


# --- erasing an account ------------------------------------------------------------


@pytest.mark.django_db
class TestErasure:
    def test_erasing_a_member_with_an_unused_licence_frees_it(self, acme, member):
        enterprise, admin = acme
        services.assign_seat(admin, member, 2)
        assert erasure.erase_account(member.account).action == erasure.DELETE
        assert given(enterprise) == 0 and row(enterprise, 2)["left"] == 5

    def test_erasing_a_member_part_way_through_frees_it_too(self, acme, member):
        enterprise, admin = acme
        services.assign_seat(admin, member, 2)
        responses.start_response(member.account, member)
        erasure.erase_account(member.account)
        assert given(enterprise) == 0 and not Response.objects.exists()

    def test_a_submitted_one_stays_counted_and_a_spare_is_freed(self, acme, member):
        enterprise, admin = acme
        spent = services.assign_seat(admin, member, 2)
        done = take_survey(spent, submitted=True)
        spare = services.assign_seat(admin, member, 2)
        assert given(enterprise) == 2

        assert erasure.erase_account(member.account).action == erasure.ANONYMISE

        spent.refresh_from_db()
        spare.refresh_from_db()
        assert spent.is_active and not spare.is_active
        assert given(enterprise) == 1  # the survey that was taken is spent for good
        assert Response.objects.get() == done
        # And the admin cannot take the spent one back afterwards either.
        refusal(lambda: services.take_back_seat(admin, spent))

    def test_erasing_the_admin_who_gave_it_leaves_the_licence_with_the_member(self, acme, member):
        enterprise, admin = acme
        second = new_member(enterprise, "dave@example.com", role="admin")
        licence = services.assign_seat(admin, member, 2)
        erasure.erase_account(admin.account)
        licence.refresh_from_db()
        assert licence.granted_by is None and licence.is_active
        assert given(enterprise) == 1
        # The remaining admin can still manage it.
        services.take_back_seat(second, licence)
        assert given(enterprise) == 0


# --- two things at the same moment (real threads) ----------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_admins_giving_the_last_licence_at_the_same_moment_give_exactly_one():
    enterprise, admin = org_with_admin("Acme")
    second = new_member(enterprise, "dave@example.com", role="admin")
    people = [new_member(enterprise, f"person{n}@example.com") for n in range(2)]
    orgs.set_seat_pool(enterprise, 2, 1)

    results = run_together(
        lambda: services.assign_seat(admin, people[0], 2),
        lambda: services.assign_seat(second, people[1], 2),
    )

    assert sum(isinstance(result, Entitlement) for result in results) == 1
    refused = [result for result in results if isinstance(result, Refused)]
    assert [str(result) for result in refused] == [NONE_LEFT]
    assert Entitlement.objects.count() == 1
    assert row(enterprise, 2) == {"tier": 2, "bought": 1, "given": 1, "set_aside": 0, "left": 0}


@pytest.mark.django_db(transaction=True)
def test_two_admins_giving_the_same_member_a_licence_at_once_give_exactly_one():
    enterprise, admin = org_with_admin("Acme")
    second = new_member(enterprise, "dave@example.com", role="admin")
    member = new_member(enterprise, "bob@example.com")
    orgs.set_seat_pool(enterprise, 2, 5)

    results = run_together(
        lambda: services.assign_seat(admin, member, 2),
        lambda: services.assign_seat(second, member, 2),
    )

    assert sum(isinstance(result, Entitlement) for result in results) == 1
    refused = [result for result in results if isinstance(result, Refused)]
    assert [str(result) for result in refused] == [services.ALREADY_HAS_ONE]
    assert member.entitlements.count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_upgrades_racing_for_the_last_licence_of_a_tier_move_exactly_one():
    enterprise, admin = org_with_admin("Acme")
    second = new_member(enterprise, "dave@example.com", role="admin")
    orgs.set_seat_pool(enterprise, 2, 2)
    orgs.set_seat_pool(enterprise, 3, 1)
    licences = [
        services.assign_seat(admin, new_member(enterprise, f"person{n}@example.com"), 2)
        for n in range(2)
    ]

    results = run_together(
        lambda: services.change_seat_tier(admin, licences[0], 3),
        lambda: services.change_seat_tier(second, licences[1], 3),
    )

    assert sum(isinstance(result, Entitlement) for result in results) == 1
    assert sum(isinstance(result, Refused) for result in results) == 1
    assert orgs.seats_given(enterprise) == {1: 0, 2: 1, 3: 1}


@pytest.mark.django_db(transaction=True)
def test_taking_back_and_starting_the_survey_at_the_same_moment_leave_no_attempt_behind():
    """Whichever goes first, the licence ends up taken back and no draft survives on it."""
    enterprise, admin = org_with_admin("Acme")
    member = new_member(enterprise, "bob@example.com")
    orgs.set_seat_pool(enterprise, 2, 1)
    licence = services.assign_seat(admin, member, 2)
    # An earlier test with real threads may have emptied every table, the survey included.
    if current_version() is None:
        SurveyVersion.objects.create(number=1, published_at=timezone.now(), question_count=0)

    results = run_together(
        lambda: services.take_back_seat(admin, licence),
        lambda: responses.start_response(member.account, member),
    )

    assert not isinstance(results[0], Exception), results[0]
    licence.refresh_from_db()
    assert not licence.is_active and not Response.objects.exists()
    assert orgs.seats_given(enterprise)[2] == 0
    # Starting either came second and found no licence, or came first and lost its draft.
    assert isinstance(results[1], responses.NoLicence | Response)


@pytest.mark.django_db
def test_stock_licence_helper_matches_what_the_service_makes(acme, member):
    """PR 1's tests make stock licences by hand; this keeps that helper honest."""
    by_hand = stock_licence(acme[1], 2)
    by_service = services.assign_seat(acme[1], member, 2)
    assert (by_hand.source, by_hand.tier) == (by_service.source, by_service.tier)
