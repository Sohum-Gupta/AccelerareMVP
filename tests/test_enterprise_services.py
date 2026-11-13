"""
Milestone 3, PR 3: the organization services. Creating one, join codes, the
people limit, roles, deactivating and reactivating. Every rule is tested here,
at the service, because the pages and the staff admin only call these.

The tests that start threads prove the row locks do their job: with the lock
removed they fail (three people get in on a two-use code).
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Account
from apps.enterprises import services
from apps.enterprises.models import Enterprise, Invite, JoinCode, Membership

from .orgs import add_member, locked_tables, new_member, org_with_admin, run_together
from .test_erasure import complete
from .test_profile import verified_account
from .test_verification import PASSWORD

Refused = services.Refused


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def bob(db):
    return verified_account("bob@example.com")


def refusal(action):
    """The plain-words message of the Refused that `action` raises."""
    with pytest.raises(Refused) as caught:
        action()
    return str(caught.value)


def expire(thing):
    type(thing).objects.filter(pk=thing.pk).update(expires_at=timezone.now() - timedelta(hours=1))


def spend_places(enterprise, count):
    """Use up places the quick way: invites that were sent, whatever became of them."""
    Invite.objects.bulk_create(
        Invite(
            enterprise=enterprise,
            email=f"guest{n}@example.com",
            token=f"spent-{enterprise.pk}-{n}",
            expires_at=timezone.now() + timedelta(days=14),
        )
        for n in range(count)
    )


# --- creating an organization --------------------------------------------------


@pytest.mark.django_db
class TestCreate:
    def test_the_creator_becomes_its_first_admin(self, bob):
        enterprise = services.create_enterprise(bob, "Acme Ltd")
        assert (enterprise.name, enterprise.slug) == ("Acme Ltd", "acme-ltd")
        assert enterprise.created_by == bob and enterprise.people_limit == 25
        membership = enterprise.memberships.get()
        assert membership.account == bob and membership.is_admin and membership.is_active
        assert membership.joined_via_invite is None and membership.joined_via_code is None

    def test_needs_a_verified_email(self, db):
        unverified = Account.objects.create_user("new@example.com", PASSWORD)
        assert "Verify your email" in refusal(
            lambda: services.create_enterprise(unverified, "Acme")
        )
        assert not Enterprise.objects.exists()

    def test_an_account_that_is_switched_off_cannot(self, bob):
        Account.objects.filter(pk=bob.pk).update(is_active=False)
        refusal(lambda: services.create_enterprise(bob, "Acme"))

    def test_the_name_is_tidied(self, bob):
        assert services.create_enterprise(bob, "  Acme    Ltd ").name == "Acme Ltd"

    @pytest.mark.parametrize("bad", ["", "   ", "A", None, "x" * 121, "Ac\x00me"])
    def test_a_missing_or_over_long_name_is_refused(self, bob, bad):
        refusal(lambda: services.create_enterprise(bob, bad))
        assert not Enterprise.objects.exists()

    def test_two_organizations_may_share_a_name_each_with_its_own_slug(self, bob):
        carol = verified_account("carol@example.com")
        first = services.create_enterprise(bob, "Acme")
        second = services.create_enterprise(carol, "Acme")
        third = services.create_enterprise(carol, "ACME")
        assert [first.slug, second.slug, third.slug] == ["acme", "acme-2", "acme-3"]

    def test_a_slug_never_shadows_a_page(self, bob):
        # /organizations/new/ is the create page.
        assert services.create_enterprise(bob, "New").slug == "new-2"

    def test_a_name_with_no_latin_letters_still_gets_a_slug(self, bob):
        first = services.create_enterprise(bob, "संगठन")
        second = services.create_enterprise(bob, "組織")
        assert (first.slug, second.slug) == ("organization", "organization-2")

    def test_an_account_can_create_three_and_no_more(self, bob):
        for n in range(3):
            services.create_enterprise(bob, f"Acme {n}")
        message = refusal(lambda: services.create_enterprise(bob, "Acme 3"))
        assert message == (
            "You have created 3 organizations, which is the limit. Contact us if you need more."
        )
        assert Enterprise.objects.count() == 3

    def test_staff_can_create_more_for_a_customer(self, bob):
        staff = Account.objects.create_superuser("root@example.com", PASSWORD)
        for n in range(3):
            services.create_enterprise(bob, f"Acme {n}")
        fourth = services.create_enterprise(bob, "Acme 3", staff=staff)
        assert fourth.created_by == staff
        assert fourth.memberships.get().account == bob and fourth.memberships.get().is_admin
        # ...and one made by staff does not use up the customer's own three.
        carol = verified_account("carol@example.com")
        services.create_enterprise(carol, "Carol 0", staff=staff)
        for n in range(1, 4):
            services.create_enterprise(carol, f"Carol {n}")

    def test_the_account_row_is_locked_so_two_clicks_take_turns(self, bob):
        with CaptureQueriesContext(connection) as captured:
            services.create_enterprise(bob, "Acme")
        assert Account._meta.db_table in locked_tables(captured.captured_queries)


@pytest.mark.django_db(transaction=True)
def test_creating_at_the_same_moment_cannot_pass_the_cap():
    bob = verified_account("bob@example.com")
    for n in range(2):
        services.create_enterprise(bob, f"Acme {n}")
    results = run_together(*[lambda: services.create_enterprise(bob, "Acme") for _ in range(3)])
    assert sum(isinstance(result, Enterprise) for result in results) == 1
    assert sum(isinstance(result, Refused) for result in results) == 2
    assert Enterprise.objects.count() == 3


# --- join codes ----------------------------------------------------------------


@pytest.mark.django_db
class TestCreateCode:
    def test_makes_ten_unambiguous_characters_good_for_thirty_days(self, acme):
        enterprise, admin = acme
        code = services.create_code(admin, 5)
        assert len(code.code) == 10 and set(code.code) <= set(services.CODE_ALPHABET)
        assert not set("0O1IL") & set(services.CODE_ALPHABET)
        assert code.enterprise == enterprise and code.created_by == admin.account
        assert (code.max_uses, code.uses, code.tier, code.revoked_at) == (5, 0, None, None)
        days = (code.expires_at - timezone.now()).total_seconds() / 86400
        assert 29.9 < days <= 30

    def test_takes_an_expiry_and_a_tier(self, acme):
        when = timezone.now() + timedelta(days=3)
        services.set_seat_pool(acme[0], 2, 1)  # a code with a tier needs the stock to cover it
        code = services.create_code(acme[1], 1, expires_at=when, tier=2)
        assert code.expires_at == when and code.tier == 2

    @pytest.mark.parametrize("bad", [0, -1, 10_001, "5", 2.0, True, None])
    def test_the_number_of_uses_must_be_a_sensible_whole_number(self, acme, bad):
        refusal(lambda: services.create_code(acme[1], bad))
        assert not JoinCode.objects.exists()

    def test_an_expiry_in_the_past_and_an_unknown_tier_are_refused(self, acme):
        past = timezone.now() - timedelta(minutes=1)
        assert "future" in refusal(lambda: services.create_code(acme[1], 1, expires_at=past))
        for tier in (0, 4, "2", True):
            refusal(lambda tier=tier: services.create_code(acme[1], 1, tier=tier))

    def test_only_an_active_admin_of_that_organization_can(self, acme):
        enterprise, _ = acme
        member = new_member(enterprise, "member@example.com")
        former = new_member(enterprise, "former@example.com", active=False)
        _, outsider = org_with_admin("Other")
        outsider.enterprise_id = enterprise.pk  # a forged membership is read again, not trusted
        for who in (member, former, outsider):
            message = refusal(lambda who=who: services.create_code(who, 5))
            assert message == "Only an admin of this organization can do that."
        assert not JoinCode.objects.exists()

    def test_how_a_code_is_typed_and_shown(self):
        assert services.normalise_code(" abcde-fghjk ") == "ABCDEFGHJK"
        assert services.normalise_code("abc de fgh jk") == "ABCDEFGHJK"
        assert services.normalise_code(None) == ""
        assert services.display_code("ABCDEFGHJK") == "ABCDE-FGHJK"


@pytest.mark.django_db
class TestRedeemCode:
    def test_makes_the_account_an_active_member_and_counts_the_use(self, acme, bob):
        enterprise, admin = acme
        code = services.create_code(admin, 5)
        membership = services.redeem_code(code.code, bob)
        assert membership.account == bob and membership.enterprise == enterprise
        assert membership.is_active and not membership.is_admin
        assert membership.joined_via_code == code and membership.joined_via_invite is None
        code.refresh_from_db()
        assert code.uses == 1

    def test_the_code_may_be_typed_in_lower_case_with_spaces_and_the_hyphen(self, acme, bob):
        code = services.create_code(acme[1], 5)
        typed = f" {code.code[:5].lower()} - {code.code[5:].lower()} "
        assert services.redeem_code(typed, bob).is_active

    @pytest.mark.parametrize("typed", ["", None, "ABCDEFGHJK", "not a code", "x" * 500])
    def test_an_unknown_code_is_refused(self, acme, bob, typed):
        services.create_code(acme[1], 5)
        assert "not valid" in refusal(lambda: services.redeem_code(typed, bob))
        assert not bob.memberships.exists()

    def test_a_revoked_code_is_refused(self, acme, bob):
        code = services.create_code(acme[1], 5)
        services.revoke_code(code, by=acme[1])
        assert "switched off" in refusal(lambda: services.redeem_code(code.code, bob))

    def test_an_expired_code_is_refused(self, acme, bob):
        code = services.create_code(acme[1], 5)
        expire(code)
        assert "expired" in refusal(lambda: services.redeem_code(code.code, bob))

    def test_a_code_stops_at_its_cap(self, acme, bob):
        code = services.create_code(acme[1], 1)
        services.redeem_code(code.code, bob)
        carol = verified_account("carol@example.com")
        assert "as many times" in refusal(lambda: services.redeem_code(code.code, carol))
        code.refresh_from_db()
        assert code.uses == 1 and not carol.memberships.exists()

    def test_an_active_member_is_told_they_already_belong(self, acme, bob):
        enterprise, admin = acme
        code = services.create_code(admin, 5)
        services.redeem_code(code.code, bob)
        for account in (bob, admin.account):
            with pytest.raises(services.AlreadyMember) as caught:
                services.redeem_code(code.code, account)
            assert str(caught.value) == "You are already a member of Acme."
        code.refresh_from_db()
        assert code.uses == 1 and enterprise.memberships.count() == 2

    def test_a_deactivated_member_cannot_come_back_with_a_code(self, acme, bob):
        _, admin = acme
        code = services.create_code(admin, 5)
        membership = services.redeem_code(code.code, bob)
        services.deactivate_membership(membership, by=admin)
        message = refusal(lambda: services.redeem_code(code.code, bob))
        assert "deactivated" in message and "reactivate" in message
        membership.refresh_from_db()
        code.refresh_from_db()
        assert not membership.is_active and code.uses == 1

    def test_needs_a_verified_email_and_a_live_account(self, acme):
        code = services.create_code(acme[1], 5)
        unverified = Account.objects.create_user("new@example.com", PASSWORD)
        assert "Verify your email" in refusal(lambda: services.redeem_code(code.code, unverified))
        gone = verified_account("gone@example.com")
        Account.objects.filter(pk=gone.pk).update(is_active=False)
        gone.refresh_from_db()
        refusal(lambda: services.redeem_code(code.code, gone))
        code.refresh_from_db()
        assert code.uses == 0

    def test_locks_the_organization_and_then_the_code(self, acme, bob):
        code = services.create_code(acme[1], 5)
        with CaptureQueriesContext(connection) as captured:
            services.redeem_code(code.code, bob)
        locking = [q["sql"] for q in captured.captured_queries if "FOR UPDATE" in q["sql"]]
        assert len(locking) == 2
        assert Enterprise._meta.db_table in locking[0] and JoinCode._meta.db_table in locking[1]
        # A lock on a join is unreliable (NOTES.md), so each is a single-table read.
        assert not any("JOIN" in sql for sql in locking)


@pytest.mark.django_db
class TestRevokeCode:
    def test_twice_keeps_the_first_date(self, acme):
        code = services.create_code(acme[1], 5)
        first = services.revoke_code(code, by=acme[1]).revoked_at
        assert first is not None
        assert services.revoke_code(code, by=acme[1]).revoked_at == first

    def test_another_organizations_admin_cannot(self, acme):
        code = services.create_code(acme[1], 5)
        _, outsider = org_with_admin("Other")
        member = new_member(acme[0], "member@example.com")
        for who in (outsider, member):
            refusal(lambda who=who: services.revoke_code(code, by=who))
        code.refresh_from_db()
        assert code.revoked_at is None

    def test_staff_can_without_being_a_member(self, acme):
        code = services.create_code(acme[1], 5)
        assert services.revoke_code(code).revoked_at is not None


@pytest.mark.django_db(transaction=True)
def test_three_people_at_once_on_a_two_use_code_make_exactly_two_members():
    enterprise, admin = org_with_admin("Acme")
    code = services.create_code(admin, 2)
    people = [verified_account(f"person{n}@example.com") for n in range(3)]

    results = run_together(
        *[lambda person=person: services.redeem_code(code.code, person) for person in people]
    )

    assert sum(isinstance(result, Membership) for result in results) == 2
    refusals = [result for result in results if isinstance(result, Refused)]
    assert len(refusals) == 1 and "as many times" in str(refusals[0])
    code.refresh_from_db()
    assert code.uses == 2
    assert enterprise.memberships.filter(joined_via_code=code).count() == 2


# --- the people limit ----------------------------------------------------------


@pytest.mark.django_db
class TestPeopleLimit:
    def test_a_new_organization_has_25_places_and_the_creator_uses_none(self, acme):
        assert services.places_left(acme[0]) == 25

    def test_every_invite_and_every_join_by_code_uses_a_place(self, acme, bob):
        enterprise, admin = acme
        spend_places(enterprise, 3)
        code = services.create_code(admin, 5)
        services.redeem_code(code.code, bob)
        services.redeem_code(code.code, verified_account("carol@example.com"))
        assert services.places_left(enterprise) == 25 - 3 - 2

    def test_revoked_expired_and_accepted_invites_still_count(self, acme):
        enterprise, _ = acme
        spend_places(enterprise, 3)
        now = timezone.now()
        revoked, expired, accepted = enterprise.invites.all()
        Invite.objects.filter(pk=revoked.pk).update(revoked_at=now)
        Invite.objects.filter(pk=expired.pk).update(expires_at=now - timedelta(days=1))
        Invite.objects.filter(pk=accepted.pk).update(accepted_at=now)
        assert services.places_left(enterprise) == 22

    def test_a_revoked_code_keeps_the_places_it_used(self, acme, bob):
        enterprise, admin = acme
        code = services.create_code(admin, 5)
        services.redeem_code(code.code, bob)
        services.revoke_code(code, by=admin)
        assert services.places_left(enterprise) == 24

    def test_another_organizations_people_do_not_count(self, acme):
        other, _ = org_with_admin("Other")
        spend_places(other, 10)
        assert services.places_left(acme[0]) == 25

    def test_the_26th_person_is_refused_by_code(self, acme, bob):
        enterprise, admin = acme
        spend_places(enterprise, 25)
        code = services.create_code(admin, 5)
        message = refusal(lambda: services.redeem_code(code.code, bob))
        assert message == "Acme cannot take more people at the moment. Ask one of its admins."
        code.refresh_from_db()
        assert code.uses == 0 and not bob.memberships.exists()

    def test_joins_by_code_alone_stop_at_the_limit(self, acme):
        enterprise, admin = acme
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=2)
        code = services.create_code(admin, 10)
        for n in range(2):
            services.redeem_code(code.code, verified_account(f"person{n}@example.com"))
        late = verified_account("late@example.com")
        refusal(lambda: services.redeem_code(code.code, late))
        enterprise.refresh_from_db()
        assert services.places_left(enterprise) == 0

    def test_staff_raising_the_limit_lets_the_next_one_in(self, acme, bob):
        enterprise, admin = acme
        spend_places(enterprise, 25)
        code = services.create_code(admin, 5)
        refusal(lambda: services.redeem_code(code.code, bob))
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=26)
        assert services.redeem_code(code.code, bob).is_active
        enterprise.refresh_from_db()
        assert services.places_left(enterprise) == 0

    def test_places_left_is_never_negative_after_the_limit_is_lowered(self, acme):
        enterprise, _ = acme
        spend_places(enterprise, 5)
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=2)
        enterprise.refresh_from_db()
        assert services.places_left(enterprise) == 0


@pytest.mark.django_db(transaction=True)
def test_two_joins_racing_for_the_last_place_give_one_member():
    enterprise, admin = org_with_admin("Acme")
    spend_places(enterprise, 24)
    # Two different codes, so only the organization's lock makes them take turns.
    codes = [services.create_code(admin, 5) for _ in range(2)]
    people = [verified_account(f"person{n}@example.com") for n in range(2)]

    results = run_together(
        *[
            lambda code=code, person=person: services.redeem_code(code.code, person)
            for code, person in zip(codes, people, strict=True)
        ]
    )

    assert sum(isinstance(result, Membership) for result in results) == 1
    assert sum(isinstance(result, Refused) for result in results) == 1
    assert services.places_left(enterprise) == 0
    assert sum(code.uses for code in JoinCode.objects.all()) == 1


# --- roles, deactivating and reactivating --------------------------------------


@pytest.mark.django_db
class TestRoles:
    def test_an_admin_can_make_a_member_an_admin_and_a_member_again(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, "member@example.com")
        assert services.set_role(member, "admin", by=admin).is_admin
        assert not services.set_role(member, "member", by=admin).is_admin

    def test_the_last_admin_cannot_be_demoted(self, acme):
        enterprise, admin = acme
        new_member(enterprise, "member@example.com")
        message = refusal(lambda: services.set_role(admin, "member", by=admin))
        assert message == (
            "An organization needs at least one admin. Make someone else an admin first."
        )
        admin.refresh_from_db()
        assert admin.is_admin

    def test_with_a_second_admin_the_first_can_step_down(self, acme):
        enterprise, admin = acme
        second = new_member(enterprise, "second@example.com", role="admin")
        assert not services.set_role(admin, "member", by=admin).is_admin
        # ...and now the second is the last one.
        refusal(lambda: services.set_role(second, "member", by=second))

    def test_a_deactivated_admin_does_not_count_as_one(self, acme):
        enterprise, admin = acme
        second = new_member(enterprise, "second@example.com", role="admin")
        services.deactivate_membership(second, by=admin)
        refusal(lambda: services.set_role(admin, "member", by=admin))

    def test_only_member_and_admin_exist(self, acme):
        member = new_member(acme[0], "member@example.com")
        for role in ("owner", "", None, "ADMIN"):
            refusal(lambda role=role: services.set_role(member, role, by=acme[1]))

    def test_a_deactivated_member_cannot_be_made_an_admin(self, acme):
        former = new_member(acme[0], "former@example.com", active=False)
        assert "Reactivate" in refusal(lambda: services.set_role(former, "admin", by=acme[1]))

    def test_only_an_active_admin_of_the_same_organization_can_change_a_role(self, acme):
        enterprise, _ = acme
        member = new_member(enterprise, "member@example.com")
        other_member = new_member(enterprise, "other@example.com")
        _, outsider = org_with_admin("Other")
        for who in (other_member, member, outsider):
            message = refusal(lambda who=who: services.set_role(member, "admin", by=who))
            assert message == "Only an admin of this organization can do that."
        member.refresh_from_db()
        assert not member.is_admin

    def test_staff_can_change_a_role_but_still_not_remove_the_last_admin(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, "member@example.com")
        assert services.set_role(member, "admin").is_admin
        services.set_role(admin, "member")
        refusal(lambda: services.set_role(member, "member"))


@pytest.mark.django_db
class TestDeactivate:
    def test_switches_the_membership_off_and_keeps_the_row(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, "member@example.com")
        done = services.deactivate_membership(member, by=admin)
        assert not done.is_active and done.deactivated_at is not None
        assert enterprise.memberships.count() == 2

    def test_twice_changes_nothing(self, acme):
        member = new_member(acme[0], "member@example.com")
        first = services.deactivate_membership(member, by=acme[1]).deactivated_at
        assert services.deactivate_membership(member, by=acme[1]).deactivated_at == first

    def test_the_last_admin_cannot_be_deactivated(self, acme):
        enterprise, admin = acme
        new_member(enterprise, "member@example.com")
        assert "at least one admin" in refusal(
            lambda: services.deactivate_membership(admin, by=admin)
        )
        admin.refresh_from_db()
        assert admin.is_active

    def test_an_admin_who_is_deactivated_stops_being_an_admin(self, acme):
        enterprise, admin = acme
        second = new_member(enterprise, "second@example.com", role="admin")
        done = services.deactivate_membership(second, by=admin)
        assert not done.is_active and not done.is_admin

    def test_an_admin_can_leave_once_there_is_another(self, acme):
        enterprise, admin = acme
        new_member(enterprise, "second@example.com", role="admin")
        assert not services.deactivate_membership(admin, by=admin).is_active

    def test_only_an_active_admin_of_the_same_organization_can(self, acme):
        enterprise, _ = acme
        member = new_member(enterprise, "member@example.com")
        _, outsider = org_with_admin("Other")
        for who in (member, outsider):
            refusal(lambda who=who: services.deactivate_membership(member, by=who))
        member.refresh_from_db()
        assert member.is_active

    def test_locks_the_organization_and_then_the_membership(self, acme):
        member = new_member(acme[0], "member@example.com")
        with CaptureQueriesContext(connection) as captured:
            services.deactivate_membership(member, by=acme[1])
        locking = [q["sql"] for q in captured.captured_queries if "FOR UPDATE" in q["sql"]]
        assert Enterprise._meta.db_table in locking[0]
        assert Membership._meta.db_table in locking[1]
        assert not any("JOIN" in sql for sql in locking)


@pytest.mark.django_db
class TestReactivate:
    def test_brings_a_member_back(self, acme):
        former = new_member(acme[0], "former@example.com", active=False)
        back = services.reactivate_membership(former, by=acme[1])
        assert back.is_active and back.deactivated_at is None

    def test_a_returning_admin_comes_back_as_a_member(self, acme):
        enterprise, admin = acme
        second = new_member(enterprise, "second@example.com", role="admin")
        services.deactivate_membership(second, by=admin)
        back = services.reactivate_membership(second, by=admin)
        assert back.is_active and not back.is_admin

    def test_an_active_member_is_left_alone(self, acme):
        member = new_member(acme[0], "member@example.com")
        assert services.reactivate_membership(member, by=acme[1]).is_active

    def test_an_erased_member_cannot_be_brought_back(self, acme):
        from apps.accounts import erasure

        enterprise, admin = acme
        member = new_member(enterprise, "member@example.com")
        complete(member.account)
        erasure.erase_account(member.account)
        assert "erased" in refusal(lambda: services.reactivate_membership(member, by=admin))
        member.refresh_from_db()
        assert not member.is_active

    def test_only_an_active_admin_of_the_same_organization_can(self, acme):
        enterprise, _ = acme
        former = new_member(enterprise, "former@example.com", active=False)
        _, outsider = org_with_admin("Other")
        refusal(lambda: services.reactivate_membership(former, by=outsider))
        refusal(lambda: services.reactivate_membership(former, by=former))
        former.refresh_from_db()
        assert not former.is_active


@pytest.mark.django_db(transaction=True)
def test_two_admins_removing_each_other_at_once_leave_one_admin():
    enterprise, first = org_with_admin("Acme")
    second = add_member(enterprise, verified_account("second@example.com"), role="admin")

    results = run_together(
        lambda: services.deactivate_membership(second, by=first),
        lambda: services.deactivate_membership(first, by=second),
    )

    assert sum(isinstance(result, Refused) for result in results) == 1
    active_admins = enterprise.memberships.filter(role="admin", status="active")
    assert active_admins.count() == 1
