"""
Milestone 3, PR 4: email invites. One address, one use, 14 days; only an account
that has verified the invited address can accept; an invite brings a deactivated
member back; a refused email keeps the invite; and erasing a person removes
their address from every invite that was sent to it.
"""

from smtplib import SMTPRecipientsRefused
from unittest import mock

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts import services as account_services
from apps.accounts.models import Account
from apps.enterprises import services
from apps.enterprises.models import Enterprise, Invite, Membership

from .orgs import new_member, org_with_admin, run_together
from .test_enterprise_services import expire, refusal, spend_places
from .test_erasure import complete
from .test_profile import second_email, verified_account
from .test_verification import PASSWORD, fake_request

Refused = services.Refused
CAROL = "carol@example.com"


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def carol(db):
    return verified_account(CAROL)


def invite(admin, email=CAROL, **extra):
    return services.invite_by_email(admin, email, **extra)[0]


# --- sending -------------------------------------------------------------------


@pytest.mark.django_db
class TestInvite:
    def test_saves_an_invite_good_for_fourteen_days(self, acme):
        enterprise, admin = acme
        made, sent = services.invite_by_email(admin, "  Carol@Example.COM ")
        assert made.enterprise == enterprise and made.email == CAROL
        assert made.created_by == admin.account and made.tier is None
        assert made.accepted_at is None and made.revoked_at is None
        days = (made.expires_at - timezone.now()).total_seconds() / 86400
        assert 13.9 < days <= 14
        assert len(made.token) >= 40
        # Without a request there is no address to build the link from: nothing is sent.
        assert sent is False and mail.outbox == []

    def test_every_invite_gets_its_own_token(self, acme):
        tokens = {invite(acme[1], f"guest{n}@example.com").token for n in range(5)}
        assert len(tokens) == 5

    def test_emails_the_link_to_the_invited_address(self, acme):
        made, sent = services.invite_by_email(acme[1], CAROL, request=fake_request())
        assert sent is True and len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [CAROL]
        assert message.subject == "[Accelerare] You are invited to join Acme"
        link = "http://testserver" + reverse("join_invite", args=[made.token])
        assert link in message.body and "14 days" in message.body
        assert services.invite_link(made, fake_request()) == link

    def test_the_email_names_the_organization_but_not_the_admin(self, acme):
        account_services.set_full_name(acme[1].account, "Alice Example")
        services.invite_by_email(acme[1], CAROL, request=fake_request())
        text = mail.outbox[0].subject + mail.outbox[0].body
        assert "Alice" not in text and acme[1].account.email not in text

    @pytest.mark.parametrize("bad", ["", None, "   ", "carol", "carol@", "a b@example.com"])
    def test_something_that_is_not_an_address_is_refused(self, acme, bad):
        assert refusal(lambda: services.invite_by_email(acme[1], bad)) == (
            "Enter a valid email address."
        )
        assert not Invite.objects.exists()

    def test_the_tier_is_stored_and_checked(self, acme):
        services.set_seat_pool(acme[0], 2, 1)  # an invite with a tier needs one left in the stock
        assert invite(acme[1], tier=2).tier == 2
        refusal(lambda: services.invite_by_email(acme[1], "other@example.com", tier=4))

    def test_only_an_active_admin_of_that_organization_can(self, acme):
        enterprise, _ = acme
        member = new_member(enterprise, "member@example.com")
        former = new_member(enterprise, "former@example.com", active=False)
        _, outsider = org_with_admin("Other")
        outsider.enterprise_id = enterprise.pk  # forged; read again, not trusted
        for who in (member, former, outsider):
            message = refusal(lambda who=who: services.invite_by_email(who, CAROL))
            assert message == "Only an admin of this organization can do that."
        assert not Invite.objects.exists()

    def test_an_address_of_an_active_member_is_refused(self, acme):
        enterprise, admin = acme
        member = new_member(enterprise, "member@example.com")
        second_email(member.account, "member.other@example.com")
        for address in ("member@example.com", "MEMBER.other@example.com", admin.account.email):
            message = refusal(lambda address=address: services.invite_by_email(admin, address))
            assert message == "Someone with that address is already a member."

    def test_an_address_a_member_only_typed_but_never_proved_does_not_block(self, acme):
        member = new_member(acme[0], "member@example.com")
        second_email(member.account, CAROL, verified=False)
        assert invite(acme[1]).email == CAROL

    def test_a_deactivated_members_address_can_be_invited(self, acme):
        new_member(acme[0], CAROL, active=False)
        assert invite(acme[1]).email == CAROL

    def test_a_second_open_invite_to_the_same_address_is_refused(self, acme):
        invite(acme[1])
        message = refusal(lambda: services.invite_by_email(acme[1], "CAROL@example.com"))
        assert "already an open invite" in message
        assert Invite.objects.count() == 1

    def test_a_new_invite_is_allowed_once_the_old_one_is_revoked_or_expired(self, acme):
        first = invite(acme[1])
        services.revoke_invite(first, by=acme[1])
        second = invite(acme[1])
        expire(second)
        invite(acme[1])
        assert Invite.objects.filter(email=CAROL).count() == 3

    def test_two_organizations_can_invite_the_same_address(self, acme):
        _, other_admin = org_with_admin("Other")
        invite(acme[1])
        assert invite(other_admin).email == CAROL

    def test_locks_the_organization(self, acme):
        with CaptureQueriesContext(connection) as captured:
            invite(acme[1])
        locking = [q["sql"] for q in captured.captured_queries if "FOR UPDATE" in q["sql"]]
        assert locking and Enterprise._meta.db_table in locking[0]
        assert not any("JOIN" in sql for sql in locking)


@pytest.mark.django_db
class TestInvitesAndThePeopleLimit:
    def test_each_invite_uses_a_place(self, acme):
        for n in range(3):
            invite(acme[1], f"guest{n}@example.com")
        assert services.places_left(acme[0]) == 22

    def test_the_26th_person_is_refused_by_invite(self, acme):
        enterprise, admin = acme
        spend_places(enterprise, 25)
        message = refusal(lambda: services.invite_by_email(admin, CAROL))
        assert message == "Acme has no places left. Contact us to add more."
        assert enterprise.invites.count() == 25

    def test_revoking_and_resending_does_not_get_round_the_limit(self, acme):
        enterprise, admin = acme
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=2)
        services.revoke_invite(invite(admin), by=admin)
        expire(invite(admin))
        refusal(lambda: services.invite_by_email(admin, CAROL))
        assert services.places_left(Enterprise.objects.get(pk=enterprise.pk)) == 0

    def test_staff_raising_the_limit_lets_the_next_invite_out(self, acme):
        enterprise, admin = acme
        spend_places(enterprise, 25)
        refusal(lambda: services.invite_by_email(admin, CAROL))
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=26)
        assert invite(admin).email == CAROL

    def test_accepting_needs_no_free_place(self, acme, carol):
        enterprise, admin = acme
        made = invite(admin)
        Enterprise.objects.filter(pk=enterprise.pk).update(people_limit=1)
        assert services.accept_invite(made.token, carol).is_active


@pytest.mark.django_db(transaction=True)
def test_two_invites_racing_for_the_last_place_send_one():
    enterprise, admin = org_with_admin("Acme")
    second = new_member(enterprise, "second@example.com", role="admin")
    spend_places(enterprise, 24)

    results = run_together(
        lambda: services.invite_by_email(admin, "one@example.com"),
        lambda: services.invite_by_email(second, "two@example.com"),
    )

    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(isinstance(result, Refused) for result in results) == 1
    assert enterprise.invites.count() == 25


@pytest.mark.django_db
class TestARefusedEmail:
    def test_keeps_the_invite_and_says_it_was_not_sent(self, acme, caplog):
        refused = SMTPRecipientsRefused({CAROL: (554, f"not verified: {CAROL}".encode())})
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=refused):
            made, sent = services.invite_by_email(acme[1], CAROL, request=fake_request())
        assert sent is False
        assert Invite.objects.get().pk == made.pk  # kept, so the admin can copy the link
        assert services.invite_link(made, fake_request()).endswith(f"/join/invite/{made.token}/")
        # Logged, without the address or the token.
        assert "Could not send an invite email (SMTPRecipientsRefused 554)" in caplog.text
        assert CAROL not in caplog.text and made.token not in caplog.text

    def test_an_outage_is_handled_the_same_way(self, acme):
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=ConnectionRefusedError):
            _, sent = services.invite_by_email(acme[1], CAROL, request=fake_request())
        assert sent is False and Invite.objects.count() == 1


# --- revoking ------------------------------------------------------------------


@pytest.mark.django_db
class TestRevoke:
    def test_twice_keeps_the_first_date(self, acme):
        made = invite(acme[1])
        first = services.revoke_invite(made, by=acme[1]).revoked_at
        assert first is not None
        assert services.revoke_invite(made, by=acme[1]).revoked_at == first

    def test_an_accepted_invite_cannot_be_revoked(self, acme, carol):
        made = invite(acme[1])
        services.accept_invite(made.token, carol)
        assert "already been accepted" in refusal(lambda: services.revoke_invite(made, by=acme[1]))

    def test_only_an_admin_of_that_organization_or_staff_can(self, acme):
        made = invite(acme[1])
        _, outsider = org_with_admin("Other")
        member = new_member(acme[0], "member@example.com")
        for who in (outsider, member):
            refusal(lambda who=who: services.revoke_invite(made, by=who))
        made.refresh_from_db()
        assert made.revoked_at is None
        assert services.revoke_invite(made).revoked_at is not None  # staff


# --- accepting -----------------------------------------------------------------


@pytest.mark.django_db
class TestAccept:
    def test_the_account_that_verified_the_address_becomes_a_member(self, acme, carol):
        enterprise, admin = acme
        made = invite(admin)
        membership = services.accept_invite(made.token, carol)
        assert membership.account == carol and membership.enterprise == enterprise
        assert membership.is_active and not membership.is_admin
        assert membership.joined_via_invite == made and membership.joined_via_code is None
        made.refresh_from_db()
        assert made.accepted_at is not None

    def test_a_verified_second_address_counts(self, acme):
        made = invite(acme[1], "carol.work@example.com")
        carol = verified_account(CAROL)
        with pytest.raises(services.WrongAddress):
            services.accept_invite(made.token, carol)
        second_email(carol, "carol.work@example.com")
        assert services.accept_invite(made.token, carol).is_active

    def test_another_account_is_told_which_address_the_invite_went_to(self, acme):
        made = invite(acme[1])
        bob = verified_account("bob@example.com")
        with pytest.raises(services.WrongAddress) as caught:
            services.accept_invite(made.token, bob)
        assert str(caught.value) == (
            "This invite was sent to carol@example.com. Log in with that address, "
            "or add and verify it on your profile, then open the link again."
        )
        assert not bob.memberships.exists()
        made.refresh_from_db()
        assert made.accepted_at is None  # still there for the right person

    def test_an_address_typed_but_not_verified_is_not_enough(self, acme):
        made = invite(acme[1])
        bob = verified_account("bob@example.com")
        second_email(bob, CAROL, verified=False)
        with pytest.raises(services.WrongAddress):
            services.accept_invite(made.token, bob)

    @pytest.mark.parametrize("token", ["", None, "nope", "x" * 500])
    def test_an_unknown_link_is_refused(self, acme, carol, token):
        invite(acme[1])
        assert refusal(lambda: services.accept_invite(token, carol)) == (
            "That invite link is not valid."
        )

    def test_works_once(self, acme, carol):
        enterprise, admin = acme
        made = invite(admin)
        membership = services.accept_invite(made.token, carol)
        with pytest.raises(services.AlreadyMember):
            services.accept_invite(made.token, carol)
        # Even after they have left, the same link does not let them back in.
        services.deactivate_membership(membership, by=admin)
        assert "already been used" in refusal(lambda: services.accept_invite(made.token, carol))
        assert enterprise.memberships.filter(status="active").count() == 1

    def test_a_revoked_invite_is_refused(self, acme, carol):
        made = invite(acme[1])
        services.revoke_invite(made, by=acme[1])
        assert "withdrawn" in refusal(lambda: services.accept_invite(made.token, carol))

    def test_an_expired_invite_is_refused(self, acme, carol):
        made = invite(acme[1])
        expire(made)
        assert "expired" in refusal(lambda: services.accept_invite(made.token, carol))
        assert not carol.memberships.exists()

    def test_brings_a_deactivated_member_back_as_a_member(self, acme, carol):
        enterprise, admin = acme
        code = services.create_code(admin, 5)
        membership = services.redeem_code(code.code, carol)
        services.set_role(membership, "admin", by=admin)
        services.deactivate_membership(membership, by=admin)

        back = services.accept_invite(invite(admin).token, carol)

        assert back.pk == membership.pk and back.is_active and not back.is_admin
        assert back.deactivated_at is None
        # The invite is now how they got in.
        assert back.joined_via_invite is not None and back.joined_via_code is None
        assert enterprise.memberships.count() == 2

    def test_someone_who_already_belongs_is_told_so_and_the_invite_stays_open(self, acme, carol):
        _, admin = acme
        made = invite(admin)
        services.redeem_code(services.create_code(admin, 5).code, carol)
        with pytest.raises(services.AlreadyMember) as caught:
            services.accept_invite(made.token, carol)
        assert str(caught.value) == "You are already a member of Acme."
        made.refresh_from_db()
        assert made.accepted_at is None

    def test_needs_a_verified_email_and_a_live_account(self, acme):
        made = invite(acme[1])
        unverified = Account.objects.create_user(CAROL, PASSWORD)
        assert "Verify your email" in refusal(
            lambda: services.accept_invite(made.token, unverified)
        )
        gone = verified_account("gone@example.com")
        Account.objects.filter(pk=gone.pk).update(is_active=False)
        gone.refresh_from_db()
        refusal(lambda: services.accept_invite(made.token, gone))

    def test_locks_the_organization_and_then_the_invite(self, acme, carol):
        made = invite(acme[1])
        with CaptureQueriesContext(connection) as captured:
            services.accept_invite(made.token, carol)
        locking = [q["sql"] for q in captured.captured_queries if "FOR UPDATE" in q["sql"]]
        assert len(locking) == 2
        assert Enterprise._meta.db_table in locking[0] and Invite._meta.db_table in locking[1]
        assert not any("JOIN" in sql for sql in locking)


@pytest.mark.django_db(transaction=True)
def test_one_invite_opened_twice_at_once_makes_one_membership():
    enterprise, admin = org_with_admin("Acme")
    carol = verified_account(CAROL)
    made = invite(admin)

    results = run_together(*[lambda: services.accept_invite(made.token, carol) for _ in range(2)])

    assert sum(isinstance(result, Membership) for result in results) == 1
    assert sum(isinstance(result, services.AlreadyMember) for result in results) == 1
    assert enterprise.memberships.filter(account=carol).count() == 1


# --- the link's address ----------------------------------------------------------


@pytest.mark.django_db
def test_the_invite_link_is_the_address_of_the_join_page(client, acme):
    """The page itself is tested in tests/test_join_pages.py."""
    made = invite(acme[1])
    address = reverse("join_invite", args=[made.token])
    assert address == f"/join/invite/{made.token}/"
    assert client.get(address).status_code == 200


# --- erasure -------------------------------------------------------------------


def addresses():
    return set(Invite.objects.values_list("email", flat=True))


@pytest.mark.django_db
class TestErasure:
    def test_a_stripped_account_loses_its_address_from_every_invite(self, acme, carol):
        enterprise, admin = acme
        _, other_admin = org_with_admin("Other")
        accepted = invite(admin)
        membership = services.accept_invite(accepted.token, carol)
        services.revoke_invite(invite(other_admin), by=other_admin)  # withdrawn
        expire(invite(other_admin))  # expired
        waiting = invite(other_admin)  # still open
        somebody_else = invite(admin, "dave@example.com")
        complete(carol)

        assert erasure.erase_account(carol).action == erasure.ANONYMISE

        assert addresses() == {"", "dave@example.com"}
        somebody_else.refresh_from_db()
        assert somebody_else.email == "dave@example.com"
        # The rows stay: the membership (deactivated) and the places they used.
        membership.refresh_from_db()
        assert not membership.is_active and membership.joined_via_invite == accepted
        assert Invite.objects.count() == 5
        assert services.places_left(enterprise) == 23
        # ...and the open one can no longer be accepted by anyone.
        assert refusal(lambda: services.accept_invite(waiting.token, verified_account(CAROL))) == (
            "That invite link is not valid."
        )

    def test_a_deleted_account_loses_its_address_from_every_invite_too(self, acme, carol):
        enterprise, admin = acme
        services.accept_invite(invite(admin).token, carol)
        _, other_admin = org_with_admin("Other")
        invite(other_admin)

        assert erasure.erase_account(carol).action == erasure.DELETE

        assert addresses() == {""}
        assert not Membership.objects.filter(enterprise=enterprise, role="member").exists()
        assert services.places_left(enterprise) == 24

    def test_an_invite_joined_with_an_address_since_removed_is_cleared_too(self, acme):
        carol = verified_account(CAROL)
        work = second_email(carol, "carol.work@example.com")
        services.accept_invite(invite(acme[1], "carol.work@example.com").token, carol)
        account_services.remove_contact(carol, work)
        erasure.erase_account(carol)
        assert addresses() == {""}

    def test_every_verified_address_of_the_account_is_cleared(self, acme):
        carol = verified_account(CAROL)
        second_email(carol, "carol.work@example.com")
        invite(acme[1], CAROL)
        invite(acme[1], "carol.work@example.com")
        erasure.erase_account(carol)
        assert addresses() == {""}

    def test_an_address_the_account_never_proved_is_left_for_its_real_owner(self, acme):
        bob = verified_account("bob@example.com")
        second_email(bob, CAROL, verified=False)
        made = invite(acme[1])
        erasure.erase_account(bob)
        made.refresh_from_db()
        assert made.email == CAROL
        assert services.accept_invite(made.token, verified_account(CAROL)).is_active

    def test_if_the_erasure_fails_the_addresses_are_still_there(self, acme, carol, monkeypatch):
        invite(acme[1])

        def boom(account):
            raise RuntimeError("boom")

        monkeypatch.setattr(erasure, "_hard_delete", boom)
        with pytest.raises(RuntimeError):
            erasure.erase_account(carol)
        assert addresses() == {CAROL}
