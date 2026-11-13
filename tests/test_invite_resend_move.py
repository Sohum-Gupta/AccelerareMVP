"""
Milestone 4, second part, PR 2: emailing an invite again, and moving it.

The rules (the founder's, 2026-11-13). An invite that has not been used can be
emailed again to the same address, or sent to a different address instead. A
move gives the invite a new link; the old one stops working, only the new
address can accept, and a licence set aside for the invite follows it. An
invite is emailed at most five times in all.

The builder's calls. Only emails the mail server accepted count towards the
five. The invite's 14 days start afresh each time an email goes out. A move
uses no further place. Only an invite that could still be accepted can be
emailed again or moved.
"""

from datetime import timedelta
from smtplib import SMTPRecipientsRefused
from unittest import mock

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts import erasure
from apps.enterprises import services
from apps.enterprises.models import Invite
from apps.entitlements.models import Entitlement

from .orgs import add_member, new_member, org_with_admin, run_together
from .test_enterprise_services import expire, refusal
from .test_profile import verified_account
from .test_response_context import fresh
from .test_seat_pools import row as stock_line
from .test_seat_services import ORGANIZATION, lock_order
from .test_verification import fake_request

CAROL = "carol@example.com"
DAN = "dan@example.com"
INVITES = "/organizations/acme/invites/"
REFUSED = mock.patch(
    "django.core.mail.EmailMessage.send",
    side_effect=SMTPRecipientsRefused({CAROL: (554, b"not verified")}),
)


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership), with two Tier 2 licences bought"""
    enterprise, admin = org_with_admin("Acme")
    services.set_seat_pool(enterprise, 2, 2)
    return enterprise, admin


@pytest.fixture
def admin(client, acme):
    """Acme's admin, logged in. Returns the admin's membership."""
    client.force_login(acme[1].account)
    return acme[1]


def sent_invite(admin, email=CAROL, **extra):
    """An invite whose first email went out."""
    made, sent = services.invite_by_email(admin, email, request=fake_request(), **extra)
    assert sent
    return made


def resend(invite, admin):
    return services.resend_invite(invite, admin, request=fake_request())


def move(invite, email, admin):
    return services.move_invite(invite, email, admin, request=fake_request())


def days_left(invite):
    return (fresh(invite).expires_at - timezone.now()).total_seconds() / 86400


def age(invite, days):
    """Pretend the invite was made this many days ago."""
    Invite.objects.filter(pk=invite.pk).update(
        expires_at=timezone.now() + timedelta(days=services.INVITE_DAYS - days)
    )


def link_of(message):
    return next(word for word in message.body.split() if "/join/invite/" in word)


def after(client, address, data=None):
    """Send a form and return the page the person lands on, as text."""
    page = client.post(address, data or {}, follow=True)
    assert page.status_code == 200
    return " ".join(page.content.decode().split())


# --- the first email counts ------------------------------------------------------------


@pytest.mark.django_db
class TestTheFirstEmailCounts:
    def test_an_invite_that_was_emailed_has_one_of_its_five(self, acme):
        assert sent_invite(acme[1]).emails_sent == 1

    def test_one_made_without_a_request_was_not_emailed(self, acme):
        made, sent = services.invite_by_email(acme[1], CAROL)
        assert sent is False and made.emails_sent == 0

    def test_a_refused_first_email_is_not_counted(self, acme):
        with REFUSED:
            made, sent = services.invite_by_email(acme[1], CAROL, request=fake_request())
        assert sent is False and made.emails_sent == 0 and fresh(made).emails_sent == 0


# --- emailing it again -----------------------------------------------------------------


@pytest.mark.django_db
class TestEmailingItAgain:
    def test_the_same_link_goes_to_the_same_address_again(self, acme):
        made = sent_invite(acme[1])
        again, sent = resend(made, acme[1])
        assert sent is True and again.pk == made.pk and again.emails_sent == 2
        assert again.token == made.token and again.email == CAROL
        assert [message.to for message in mail.outbox] == [[CAROL], [CAROL]]
        assert link_of(mail.outbox[0]) == link_of(mail.outbox[1])
        assert Invite.objects.count() == 1  # it used no further place

    def test_the_fourteen_days_start_afresh(self, acme):
        made = sent_invite(acme[1])
        age(made, 10)
        assert 3.9 < days_left(made) < 4.1
        resend(made, acme[1])
        assert 13.9 < days_left(made) <= 14

    def test_the_sixth_email_is_refused(self, acme):
        made = sent_invite(acme[1])
        for _ in range(4):
            resend(made, acme[1])
        assert fresh(made).emails_sent == 5 == services.MAX_INVITE_EMAILS
        said = refusal(lambda: resend(made, acme[1]))
        assert said == services.EMAILED_ENOUGH and "5 times" in said
        assert len(mail.outbox) == 5 and fresh(made).emails_sent == 5

    def test_a_refused_send_is_not_counted_and_does_not_restart_the_days(self, acme):
        made = sent_invite(acme[1])
        age(made, 10)
        with REFUSED:
            again, sent = resend(made, acme[1])
        assert sent is False and again.emails_sent == 1 and fresh(made).emails_sent == 1
        assert days_left(made) < 4.1
        assert again.token == made.token  # the admin can still copy the same link

    @pytest.mark.parametrize("ended", ["accepted", "withdrawn", "expired", "erased"])
    def test_only_an_invite_that_can_still_be_accepted(self, acme, ended):
        made = sent_invite(acme[1])
        carol = verified_account(CAROL)
        if ended == "accepted":
            services.accept_invite(made.token, carol)
        elif ended == "withdrawn":
            services.revoke_invite(made, by=acme[1])
        elif ended == "expired":
            expire(made)
        else:
            erasure.erase_account(carol)
        mail.outbox.clear()
        refusal(lambda: resend(made, acme[1]))
        refusal(lambda: move(made, DAN, acme[1]))
        assert mail.outbox == [] and fresh(made).emails_sent == 1
        assert fresh(made).token == made.token

    def test_only_an_active_admin_of_that_organization_can(self, acme):
        enterprise, admin = acme
        made = sent_invite(admin)
        member = new_member(enterprise, "member@example.com")
        _, outsider = org_with_admin("Other")
        outsider.enterprise_id = enterprise.pk  # forged; read again, not trusted
        for who in (member, outsider):
            for action in (lambda who=who: resend(made, who), lambda who=who: move(made, DAN, who)):
                assert refusal(action) == "Only an admin of this organization can do that."
        assert len(mail.outbox) == 1 and fresh(made).email == CAROL


@pytest.mark.django_db(transaction=True)
def test_two_clicks_at_the_same_moment_cannot_send_a_sixth_email():
    _, admin = org_with_admin("Acme")
    made = sent_invite(admin)
    Invite.objects.filter(pk=made.pk).update(emails_sent=4)
    results = run_together(lambda: resend(made, admin), lambda: resend(made, admin))
    assert sum(isinstance(result, services.Refused) for result in results) == 1, results
    assert fresh(made).emails_sent == 5


# --- moving it to another address ------------------------------------------------------


@pytest.mark.django_db
class TestMovingIt:
    def test_the_invite_goes_to_the_new_address_with_a_new_link(self, acme):
        made = sent_invite(acme[1])
        moved, sent = move(made, "  Dan@Example.COM ", acme[1])
        assert sent is True and moved.pk == made.pk
        assert moved.email == DAN and moved.token != made.token and moved.emails_sent == 2
        assert mail.outbox[1].to == [DAN]
        assert link_of(mail.outbox[1]).endswith(f"/join/invite/{moved.token}/")
        assert Invite.objects.count() == 1  # still one invite, so one place

    def test_the_old_link_is_simply_unknown_and_reveals_nothing(self, acme):
        made = sent_invite(acme[1])
        carol = verified_account(CAROL)
        move(made, DAN, acme[1])
        said = refusal(lambda: services.check_invite(made.token, carol))
        assert said == "That invite link is not valid." and DAN not in said
        assert refusal(lambda: services.accept_invite(made.token, carol)) == said
        assert not carol.memberships.exists()

    def test_only_the_new_address_can_accept(self, acme):
        made = sent_invite(acme[1])
        carol, dan = verified_account(CAROL), verified_account(DAN)
        moved, _sent = move(made, DAN, acme[1])
        wrong = refusal(lambda: services.accept_invite(moved.token, carol))
        assert wrong.startswith(f"This invite was sent to {DAN}.")
        member = services.accept_invite(moved.token, dan)
        assert member.account == dan and member.joined_via_invite == moved

    def test_a_licence_set_aside_follows_the_invite(self, acme):
        enterprise, admin = acme
        made = sent_invite(admin, tier=2)
        assert stock_line(enterprise, 2)["set_aside"] == 1
        moved, _sent = move(made, DAN, admin)
        assert stock_line(enterprise, 2) == {
            "tier": 2,
            "bought": 2,
            "given": 0,
            "set_aside": 1,
            "left": 1,
        }
        member = services.accept_invite(moved.token, verified_account(DAN))
        (licence,) = Entitlement.objects.filter(membership=member)
        assert licence.tier == 2 and licence.source == "seat"
        assert stock_line(enterprise, 2)["given"] == 1

    def test_it_uses_no_further_place(self, acme):
        enterprise, admin = acme
        made = sent_invite(admin)
        before = services.places_left(enterprise)
        move(made, DAN, admin)
        assert services.places_left(enterprise) == before

    def test_the_fourteen_days_start_afresh(self, acme):
        made = sent_invite(acme[1])
        age(made, 10)
        move(made, DAN, acme[1])
        assert 13.9 < days_left(made) <= 14

    def test_a_move_counts_towards_the_five(self, acme):
        made = sent_invite(acme[1])
        for number in range(4):
            move(made, f"person{number}@example.com", acme[1])
        assert fresh(made).emails_sent == 5
        assert refusal(lambda: move(made, DAN, acme[1])) == services.EMAILED_ENOUGH
        assert fresh(made).email == "person3@example.com"  # the refused move changed nothing
        assert len(mail.outbox) == 5

    def test_if_the_email_is_refused_the_move_still_happens_uncounted(self, acme):
        """The admin copies the new link; the old one is dead either way."""
        made = sent_invite(acme[1])
        age(made, 10)
        with REFUSED:
            moved, sent = move(made, DAN, acme[1])
        assert sent is False and moved.email == DAN and moved.token != made.token
        assert moved.emails_sent == 1 and days_left(made) < 4.1

    @pytest.mark.parametrize("bad", ["", "   ", "not-an-address", "a@b", None])
    def test_something_that_is_not_an_address_is_refused(self, acme, bad):
        made = sent_invite(acme[1])
        assert refusal(lambda: move(made, bad, acme[1])) == "Enter a valid email address."
        assert fresh(made).email == CAROL and fresh(made).token == made.token

    def test_the_same_address_is_refused(self, acme):
        made = sent_invite(acme[1])
        assert "already goes to" in refusal(lambda: move(made, "CAROL@example.com", acme[1]))
        assert len(mail.outbox) == 1

    def test_an_address_of_an_active_member_is_refused(self, acme):
        enterprise, admin = acme
        new_member(enterprise, DAN)
        made = sent_invite(admin)
        assert refusal(lambda: move(made, DAN, admin)) == (
            "Someone with that address is already a member."
        )

    def test_an_address_with_an_open_invite_of_its_own_is_refused(self, acme):
        made = sent_invite(acme[1])
        sent_invite(acme[1], DAN)
        assert refusal(lambda: move(made, DAN, acme[1])) == (
            "There is already an open invite to that address."
        )
        assert fresh(made).email == CAROL

    def test_the_organization_is_locked_first(self, acme):
        made = sent_invite(acme[1])
        with CaptureQueriesContext(connection) as queries:
            move(made, DAN, acme[1])
        assert lock_order(queries)[0] == ORGANIZATION


@pytest.mark.django_db(transaction=True)
def test_two_invites_moved_to_one_address_at_the_same_moment_leave_one_there():
    enterprise, first = org_with_admin("Acme")
    second = add_member(enterprise, verified_account("second@example.com"), role="admin")
    one, two = sent_invite(first, "one@example.com"), sent_invite(first, "two@example.com")
    results = run_together(lambda: move(one, DAN, first), lambda: move(two, DAN, second))
    assert sum(isinstance(result, services.Refused) for result in results) == 1, results
    assert Invite.objects.filter(email=DAN).count() == 1


# --- the invites page ------------------------------------------------------------------


@pytest.mark.django_db
class TestTheInvitesPage:
    def test_an_open_invite_says_how_often_it_was_emailed_and_offers_both(self, client, admin):
        made = sent_invite(admin)
        page = client.get(INVITES)
        row = page.context["rows"][0]
        assert row["emails_sent"] == 1 and row["can_email"] is True
        assert page.context["max_emails"] == 5
        text = " ".join(page.content.decode().split())
        assert "Emailed 1 of 5 times." in text
        assert f'action="{INVITES}{made.pk}/resend/"' in text
        assert f'action="{INVITES}{made.pk}/move/"' in text
        assert "Email it again" in text and "Send it to a different address instead" in text

    def test_at_the_cap_it_offers_neither_and_says_why(self, client, admin):
        made = sent_invite(admin)
        Invite.objects.filter(pk=made.pk).update(emails_sent=5)
        page = client.get(INVITES)
        text = " ".join(page.content.decode().split())
        assert page.context["rows"][0]["can_email"] is False
        assert "Emailed 5 of 5 times, the most allowed." in text
        assert "/resend/" not in text and "/move/" not in text
        assert f'action="{INVITES}{made.pk}/revoke/"' in text  # it can still be withdrawn

    def test_an_invite_that_is_over_offers_neither(self, client, admin):
        made = sent_invite(admin)
        services.revoke_invite(made, by=admin)
        text = client.get(INVITES).content.decode()
        assert "/resend/" not in text and "/move/" not in text and "data-emailed" not in text

    def test_the_button_emails_it_again(self, client, admin):
        made = sent_invite(admin)
        text = after(client, f"{INVITES}{made.pk}/resend/")
        assert f"The invite was emailed to {CAROL} again." in text
        assert "Emailed 2 of 5 times." in text and len(mail.outbox) == 2

    def test_when_the_email_cannot_be_sent_the_page_says_to_copy_the_link(self, client, admin):
        made = sent_invite(admin)
        with REFUSED:
            text = after(client, f"{INVITES}{made.pk}/resend/")
        assert f"We could not send the email to {CAROL}." in text
        assert "Emailed 1 of 5 times." in text

    def test_the_form_moves_it(self, client, admin):
        made = sent_invite(admin)
        text = after(client, f"{INVITES}{made.pk}/move/", {"email": DAN})
        assert f"The invite now goes to {DAN} and has been emailed there." in text
        assert "The old link no longer works." in text
        moved = fresh(made)
        assert moved.email == DAN and f"/join/invite/{moved.token}/" in text
        assert made.token not in text and CAROL not in text

    def test_a_move_whose_email_cannot_be_sent_says_to_copy_the_new_link(self, client, admin):
        made = sent_invite(admin)
        with REFUSED:
            text = after(client, f"{INVITES}{made.pk}/move/", {"email": DAN})
        assert f"The invite now goes to {DAN}, but we could not send the email." in text
        assert f"/join/invite/{fresh(made).token}/" in text

    def test_a_refusal_is_shown_and_changes_nothing(self, client, admin):
        made = sent_invite(admin)
        text = after(client, f"{INVITES}{made.pk}/move/", {"email": "nonsense"})
        assert "Enter a valid email address." in text and fresh(made).email == CAROL

    def test_the_two_addresses_take_a_post_only(self, client, admin):
        made = sent_invite(admin)
        for action in ("resend", "move"):
            assert client.get(f"{INVITES}{made.pk}/{action}/").status_code == 405
        assert len(mail.outbox) == 1

    def test_another_organizations_invite_is_not_found(self, client, admin):
        _, other_admin = org_with_admin("Globex")
        theirs = sent_invite(other_admin, "theirs@example.com")
        mail.outbox.clear()
        for address in ("/organizations/acme/invites/", "/organizations/globex/invites/"):
            assert client.post(f"{address}{theirs.pk}/resend/").status_code == 404
            assert client.post(f"{address}{theirs.pk}/move/", {"email": DAN}).status_code == 404
        now = fresh(theirs)
        assert (now.email, now.token, now.emails_sent) == (theirs.email, theirs.token, 1)
        assert mail.outbox == []

    def test_a_member_who_is_not_an_admin_cannot(self, client, acme):
        enterprise, admin = acme
        made = sent_invite(admin)
        member = new_member(enterprise, "member@example.com")
        client.force_login(member.account)
        assert client.post(f"{INVITES}{made.pk}/resend/").status_code == 404
        assert client.post(f"{INVITES}{made.pk}/move/", {"email": DAN}).status_code == 404
        assert fresh(made).email == CAROL and len(mail.outbox) == 1
