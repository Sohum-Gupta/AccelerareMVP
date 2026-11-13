"""
Milestone 3, PR 9: the admin's join codes and invites pages.

/organizations/<slug>/codes/ lists the organization's join codes with their
uses, makes a new one and switches one off. /organizations/<slug>/invites/
lists its invites, sends one, withdraws one and shows the link of each open
invite for the admin to copy. Both say how many places the organization has
left ("18 of 25 places left"), and so does the dashboard.

Who may open these pages, and that one organization never sees another's codes
or invites, is in tests/test_tenant_isolation.py.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

from datetime import timedelta
from smtplib import SMTPRecipientsRefused
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts import erasure
from apps.enterprises import services as orgs
from apps.enterprises.models import Enterprise, Invite, JoinCode

from .orgs import new_member
from .test_enterprise_services import expire, spend_places
from .test_erasure import complete
from .test_profile import verified_account
from .test_response_context import acme, fresh  # noqa: F401

ACME = "/organizations/acme/"
CODES = "/organizations/acme/codes/"
INVITES = "/organizations/acme/invites/"
CAROL = "carol@example.com"


@pytest.fixture
def admin(client, acme):
    """Acme's admin, logged in. Returns the admin's membership."""
    client.force_login(acme[1].account)
    return acme[1]


def html(client, address):
    page = client.get(address)
    assert page.status_code == 200, f"{address} answered {page.status_code}"
    return page.content.decode()


def after(client, address, data=None):
    """Send a form and return the page the person lands on, as (address, text)."""
    page = client.post(address, data or {}, follow=True)
    assert page.status_code == 200
    landed = page.redirect_chain[-1][0] if page.redirect_chain else address
    return landed, page.content.decode()


def rows(client, address):
    return client.get(address).context["rows"]


# --- join codes ----------------------------------------------------------------


@pytest.mark.django_db
class TestTheCodesPage:
    def test_it_starts_empty_with_the_form_filled_in(self, client, admin):
        text = html(client, CODES)
        assert "No join codes yet." in text
        assert 'name="max_uses"' in text and 'value="10"' in text
        assert 'name="days"' in text and 'value="30"' in text

    def test_creating_a_code_shows_it_as_xxxxx_xxxxx(self, client, admin):
        landed, text = after(client, CODES, {"max_uses": "12", "days": "7"})
        code = JoinCode.objects.get()
        shown = orgs.display_code(code.code)
        assert landed == CODES
        assert f"Join code {shown} is ready." in text
        assert code.max_uses == 12 and code.created_by == admin.account
        assert code.enterprise == admin.enterprise and code.tier is None
        lasts = code.expires_at - timezone.now()
        assert timedelta(days=6, hours=23) < lasts <= timedelta(days=7)
        row = rows(client, CODES)[0]
        assert row["code"] == shown and row["state"] == "active"
        assert "Used 0 of 12 times" in text and "Works until" in text

    @pytest.mark.parametrize(
        ("data", "why"),
        [
            ({"max_uses": "", "days": "30"}, "Enter how many people may use the code."),
            ({"max_uses": "0", "days": "30"}, "Choose a number from 1 to 10,000."),
            ({"max_uses": "10001", "days": "30"}, "Choose a number from 1 to 10,000."),
            ({"max_uses": "ten", "days": "30"}, "Enter a whole number."),
            ({"max_uses": "5", "days": "0"}, "Choose a number of days from 1 to 365."),
            ({"max_uses": "5", "days": "366"}, "Choose a number of days from 1 to 365."),
            ({"max_uses": "5", "days": ""}, "Enter how many days the code should last."),
        ],
    )
    def test_a_number_out_of_range_is_asked_for_again(self, client, admin, data, why):
        page = client.post(CODES, data)
        assert page.status_code == 200 and why in page.content.decode()
        assert not JoinCode.objects.exists()

    def test_the_uses_are_shown(self, client, admin):
        code = orgs.create_code(admin, 2)
        orgs.redeem_code(code.code, verified_account(CAROL))
        assert "Used 1 of 2 times" in html(client, CODES)

    def test_switching_a_code_off(self, client, admin):
        code = orgs.create_code(admin, 5)
        assert f"{CODES}{code.pk}/revoke/" in html(client, CODES)
        landed, text = after(client, f"{CODES}{code.pk}/revoke/")
        assert landed == CODES
        assert f"Join code {orgs.display_code(code.code)} is switched off." in text
        assert fresh(code).revoked_at is not None
        assert rows(client, CODES)[0]["state"] == "revoked"
        assert "Switched off on" in text and f"{CODES}{code.pk}/revoke/" not in text

    def test_each_state_is_named_and_only_a_working_code_can_be_switched_off(self, client, admin):
        expired = orgs.create_code(admin, 5)
        expire(expired)
        used_up = orgs.create_code(admin, 1)
        orgs.redeem_code(used_up.code, verified_account(CAROL))
        working = orgs.create_code(admin, 5)
        states = {row["id"]: row["state"] for row in rows(client, CODES)}
        assert states == {expired.pk: "expired", used_up.pk: "used_up", working.pk: "active"}
        text = html(client, CODES)
        assert "Expired on" in text and "Used up" in text
        assert f"{CODES}{working.pk}/revoke/" in text
        for dead in (expired, used_up):
            assert f"{CODES}{dead.pk}/revoke/" not in text

    def test_working_codes_come_first(self, client, admin):
        old = orgs.create_code(admin, 5)
        revoked = orgs.create_code(admin, 5)
        orgs.revoke_code(revoked, by=admin)
        assert [row["id"] for row in rows(client, CODES)] == [old.pk, revoked.pk]

    def test_switch_off_is_post_only_and_an_unknown_code_is_not_found(self, client, admin):
        code = orgs.create_code(admin, 5)
        assert client.get(f"{CODES}{code.pk}/revoke/").status_code == 405
        assert client.post(f"{CODES}999999/revoke/").status_code == 404
        assert fresh(code).revoked_at is None

    def test_no_licence_comes_with_a_code_or_an_invite_unless_one_is_chosen(self, client, admin):
        """The tier drop-down and what it does are in tests/test_tier_on_join.py."""
        for address in (CODES, INVITES):
            assert '<option value="" selected>No licence</option>' in html(client, address)


# --- invites -------------------------------------------------------------------


@pytest.mark.django_db
class TestTheInvitesPage:
    def test_it_starts_empty(self, client, admin):
        text = html(client, INVITES)
        assert "No invites yet." in text and 'name="email"' in text
        assert "lasts 14 days" in text

    def test_sending_an_invite_emails_the_link(self, client, admin):
        landed, text = after(client, INVITES, {"email": " Carol@Example.com "})
        invite = Invite.objects.get()
        assert landed == INVITES and f"Invite sent to {CAROL}." in text
        assert invite.email == CAROL and invite.created_by == admin.account
        assert invite.enterprise == admin.enterprise and invite.tier is None
        [message] = mail.outbox
        assert message.to == [CAROL]
        assert f"/join/invite/{invite.token}/" in message.body and "Acme" in message.body

    def test_an_open_invite_shows_its_link_to_copy(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        row = rows(client, INVITES)[0]
        link = f"http://testserver/join/invite/{invite.token}/"
        assert row["state"] == "pending" and row["link"] == link
        text = html(client, INVITES)
        assert f'value="{link}"' in text and "data-copy=" in text
        assert CAROL in text and "Waiting" in text
        assert f"{INVITES}{invite.pk}/revoke/" in text

    def test_if_the_email_cannot_be_sent_the_invite_is_kept_and_the_page_says_so(
        self, client, admin
    ):
        refused = SMTPRecipientsRefused({CAROL: (554, b"not verified")})
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=refused):
            landed, text = after(client, INVITES, {"email": CAROL})
        invite = Invite.objects.get()
        assert landed == INVITES
        assert "is saved, but we could not send the email." in text
        assert "Invite sent to" not in text
        assert f"/join/invite/{invite.token}/" in text  # there to be copied

    @pytest.mark.parametrize(
        ("typed", "why"),
        [("", "Enter an email address."), ("not an address", "Enter a valid email address.")],
    )
    def test_something_that_is_not_an_address_is_asked_for_again(self, client, admin, typed, why):
        page = client.post(INVITES, {"email": typed})
        assert page.status_code == 200 and why in page.content.decode()
        assert not Invite.objects.exists() and not mail.outbox

    def test_the_rules_refusals_are_shown_in_plain_words(self, client, acme, admin):
        new_member(acme[0], CAROL)
        page = client.post(INVITES, {"email": CAROL})
        assert "Someone with that address is already a member." in page.content.decode()
        after(client, INVITES, {"email": "dave@example.com"})
        page = client.post(INVITES, {"email": "dave@example.com"})
        assert "There is already an open invite to that address." in page.content.decode()
        assert Invite.objects.count() == 1 and len(mail.outbox) == 1

    def test_withdrawing_an_invite(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        landed, text = after(client, f"{INVITES}{invite.pk}/revoke/")
        assert landed == INVITES and "The invite has been withdrawn." in text
        assert fresh(invite).revoked_at is not None
        row = rows(client, INVITES)[0]
        assert row["state"] == "revoked" and row["link"] == ""
        assert "Withdrawn on" in text and invite.token not in text
        assert f"{INVITES}{invite.pk}/revoke/" not in text

    def test_an_accepted_invite_has_no_link_and_cannot_be_withdrawn(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        orgs.accept_invite(invite.token, verified_account(CAROL))
        row = rows(client, INVITES)[0]
        assert row["state"] == "accepted" and row["link"] == ""
        text = html(client, INVITES)
        assert "Accepted on" in text and invite.token not in text
        _, text = after(client, f"{INVITES}{invite.pk}/revoke/")
        assert "That invite has already been accepted." in text
        assert fresh(invite).revoked_at is None

    def test_an_expired_invite_has_no_link(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        expire(invite)
        row = rows(client, INVITES)[0]
        assert row["state"] == "expired" and row["link"] == ""
        assert "Expired on" in html(client, INVITES)

    def test_an_invite_to_someone_since_erased_shows_no_address_and_no_link(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        carol = verified_account(CAROL)
        complete(carol)
        erasure.erase_account(carol)
        row = rows(client, INVITES)[0]
        assert row["email"] == "" and row["state"] == "erased" and row["link"] == ""
        text = html(client, INVITES)
        assert "Address removed" in text and CAROL not in text and invite.token not in text

    def test_open_invites_come_first(self, client, admin):
        withdrawn, _ = orgs.invite_by_email(admin, "old@example.com")
        orgs.revoke_invite(withdrawn, by=admin)
        waiting, _ = orgs.invite_by_email(admin, CAROL)
        newest, _ = orgs.invite_by_email(admin, "dave@example.com")
        orgs.revoke_invite(newest, by=admin)
        ids = [row["id"] for row in rows(client, INVITES)]
        assert ids == [waiting.pk, newest.pk, withdrawn.pk]

    def test_withdraw_is_post_only_and_an_unknown_invite_is_not_found(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        assert client.get(f"{INVITES}{invite.pk}/revoke/").status_code == 405
        assert client.post(f"{INVITES}999999/revoke/").status_code == 404
        assert fresh(invite).revoked_at is None


# --- places left -----------------------------------------------------------------


@pytest.mark.django_db
class TestPlacesLeft:
    def test_every_admin_page_says_how_many_are_left(self, client, acme, admin):
        spend_places(acme[0], 6)
        code = orgs.create_code(admin, 5)
        orgs.redeem_code(code.code, verified_account(CAROL))
        for address in (ACME, CODES, INVITES):
            page = client.get(address)
            assert page.context["places"] == {"left": 18, "limit": 25}, address
            assert "18 of 25 places left" in page.content.decode(), address

    def test_a_withdrawn_invite_still_uses_its_place(self, client, admin):
        invite, _ = orgs.invite_by_email(admin, CAROL)
        after(client, f"{INVITES}{invite.pk}/revoke/")
        assert "24 of 25 places left" in html(client, INVITES)

    def test_with_none_left_the_page_says_so_and_an_invite_is_refused(self, client, acme, admin):
        spend_places(acme[0], 25)
        for address in (CODES, INVITES):
            text = html(client, address)
            assert "0 of 25 places left" in text
            assert "Nobody else can be invited or join with a code" in text
        page = client.post(INVITES, {"email": CAROL})
        assert "Acme has no places left." in page.content.decode()
        assert Invite.objects.count() == 25 and not mail.outbox

    def test_staff_raising_the_limit_shows_at_once(self, client, acme, admin):
        spend_places(acme[0], 25)
        Enterprise.objects.filter(pk=acme[0].pk).update(people_limit=40)
        assert "15 of 40 places left" in html(client, INVITES)

    def test_the_dashboard_links_to_both_pages_for_an_admin_only(self, client, acme, admin):
        text = html(client, ACME)
        assert f'href="{CODES}"' in text and f'href="{INVITES}"' in text
        member = new_member(acme[0], CAROL)
        client.force_login(member.account)
        text = html(client, ACME)
        assert CODES not in text and INVITES not in text and "places left" not in text
