"""
Milestone 5, PR 2: a member is emailed when an admin gives them a licence.

The rule (the founder's default, accepted 2026-11-13). When an organization's
admin gives a member a licence, the member gets an email saying so. It is sent
in the background: giving the licence queues a job, and the worker sends the
email. The admin's page waits for nothing.

The builder's calls. The email names the organization and never the tier. It
goes to the address the organization knows the member by. Nothing is sent if
it would no longer be true by the time the worker runs. The queue never holds
an address.
"""

import importlib
from smtplib import SMTPRecipientsRefused
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.job_handlers import send_licence_email
from apps.entitlements.services import LICENCE_EMAIL
from apps.jobs import services as jobs
from apps.jobs.models import Job

from .orgs import new_member, org_with_admin
from .test_enterprise_services import refusal
from .test_profile import second_email, verified_account
from .test_response_context import fresh
from .test_seat_pools import take_survey

BOB = "bob@example.com"


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership), with three Tier 2 licences bought"""
    enterprise, admin = org_with_admin("Acme")
    orgs.set_seat_pool(enterprise, 2, 3)
    return enterprise, admin


@pytest.fixture
def bob(acme):
    return new_member(acme[0], BOB)


def given(acme, member, tier=2):
    """The admin gives the member a licence. Returns it; the email is still only queued."""
    return licences.assign_seat(acme[1], member, tier)


# --- giving a licence queues the email ------------------------------------------------------


@pytest.mark.django_db
class TestGivingALicenceQueuesTheEmail:
    def test_one_job_is_queued_and_nothing_is_sent_until_the_worker_runs(self, acme, bob):
        licence = given(acme, bob)
        queued = Job.objects.get()
        assert (queued.kind, queued.status) == (LICENCE_EMAIL, "queued")
        assert queued.payload == {"entitlement_id": licence.pk}
        assert mail.outbox == []  # the admin's page waited for nothing

    def test_the_queue_holds_a_number_and_never_an_address(self, acme, bob):
        given(acme, bob)
        assert BOB not in str(Job.objects.values().get())

    def test_a_refused_licence_queues_nothing(self, acme, bob):
        orgs.set_seat_pool(acme[0], 2, 0)
        refusal(lambda: given(acme, bob))
        assert not Job.objects.exists()

    def test_an_admin_giving_themselves_a_licence_is_not_emailed_about_it(self, acme):
        given(acme, acme[1])
        assert not Job.objects.exists()

    def test_changing_a_tier_or_taking_a_licence_back_queues_nothing_more(self, acme, bob):
        orgs.set_seat_pool(acme[0], 3, 1)
        licence = given(acme, bob)
        licences.change_seat_tier(acme[1], licence, 3)
        licences.take_back_seat(acme[1], licence)
        assert Job.objects.count() == 1

    def test_joining_with_an_invite_or_code_that_comes_with_a_licence_sends_no_email(self, acme):
        """They were told on the page they joined from."""
        code = orgs.create_code(acme[1], 1, tier=2)
        member = orgs.redeem_code(code.code, verified_account("carol@example.com"))
        assert member.entitlements.count() == 1
        assert not Job.objects.filter(kind=LICENCE_EMAIL).exists()


# --- the worker sends it --------------------------------------------------------------------


@pytest.mark.django_db
class TestTheWorkerSendsIt:
    def test_the_member_is_told_which_organization_and_where_to_start(self, acme, bob):
        given(acme, bob)
        assert jobs.run_due() == 1
        (message,) = mail.outbox
        assert message.to == [BOB]
        assert message.subject == "[Accelerare] You have a licence to take the survey for Acme"
        assert "Acme has given you a licence to take the Accelerare survey for it." in message.body
        assert "http://localhost:8000/survey/start/acme/" in message.body
        assert "They never see your answers." in message.body
        assert "Tier" not in message.subject + message.body  # the level is not named
        assert Job.objects.get().status == "done"

    def test_it_goes_to_the_address_the_organization_knows_them_by(self, acme):
        invite, _sent = orgs.invite_by_email(acme[1], "work@example.com")
        account = verified_account("personal@example.com")
        second_email(account, "work@example.com")
        member = orgs.accept_invite(invite.token, account)
        given(acme, member)
        jobs.run_due()
        assert mail.outbox[-1].to == ["work@example.com"]

    def test_each_licence_given_is_one_email(self, acme, bob):
        carol = new_member(acme[0], "carol@example.com")
        given(acme, bob)
        given(acme, carol)
        jobs.run_due()
        assert sorted(message.to[0] for message in mail.outbox) == [BOB, "carol@example.com"]

    @pytest.mark.parametrize(
        "meanwhile", ["taken back", "started", "member left", "erased", "licence deleted"]
    )
    def test_nothing_is_sent_if_it_is_no_longer_true(self, acme, bob, meanwhile):
        licence = given(acme, bob)
        if meanwhile == "taken back":
            licences.take_back_seat(acme[1], licence)
        elif meanwhile == "started":
            take_survey(licence)
        elif meanwhile == "member left":
            orgs.deactivate_membership(bob, by=acme[1])
        elif meanwhile == "erased":
            take_survey(licence, submitted=True)  # so the account is stripped, not deleted
            erasure.erase_account(bob.account)
        else:
            erasure.erase_account(bob.account)  # no survey: the licence goes with the account
        assert jobs.run_due() == 1
        assert mail.outbox == []
        done = Job.objects.get()
        assert (done.status, done.last_error) == ("done", "")  # not a failure: nothing to do

    def test_an_account_marked_erased_is_never_written_to_even_if_still_a_member(self, acme, bob):
        """Erasing also deactivates the membership; this holds even if that step were missed."""
        given(acme, bob)
        Account.objects.filter(pk=bob.account_id).update(anonymised_at=timezone.now())
        jobs.run_due()
        assert mail.outbox == [] and Job.objects.get().status == "done"

    def test_a_refused_send_is_tried_again_and_keeps_the_address_out_of_the_record(
        self, acme, bob, caplog
    ):
        given(acme, bob)
        refused = SMTPRecipientsRefused({BOB: (554, f"not verified: {BOB}".encode())})
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=refused):
            jobs.run_due()
        waiting = Job.objects.get()
        assert (waiting.status, waiting.attempts) == ("queued", 1)
        assert waiting.last_error == "SMTPRecipientsRefused"
        assert BOB not in caplog.text and BOB not in waiting.last_error
        assert mail.outbox == []
        jobs.run_due(now=fresh(waiting).run_after)  # two minutes later the mail server is back
        assert [message.to for message in mail.outbox] == [[BOB]]
        assert Job.objects.get().status == "done"

    def test_run_twice_by_mistake_it_would_send_twice_and_that_is_accepted(self, acme, bob):
        """The one job that is not safe to repeat; a crash at the wrong moment can do this."""
        licence = given(acme, bob)
        send_licence_email(entitlement_id=licence.pk)
        send_licence_email(entitlement_id=licence.pk)
        assert len(mail.outbox) == 2

    def test_a_licence_number_that_means_nothing_is_ignored(self, db):
        send_licence_email(entitlement_id=999_999)
        assert mail.outbox == []


# --- the page does not wait -----------------------------------------------------------------


@pytest.mark.django_db
class TestTheLicencesPageDoesNotWait:
    def test_the_give_button_queues_the_email_even_when_the_mail_server_is_down(
        self, client, acme, bob
    ):
        client.force_login(acme[1].account)
        down = mock.patch("django.core.mail.EmailMessage.send", side_effect=OSError("no route"))
        with down:
            page = client.post(
                f"/organizations/acme/licences/members/{bob.pk}/give/", {"tier": "2"}, follow=True
            )
        assert page.status_code == 200 and "now has a Tier 2 licence" in page.content.decode()
        assert bob.entitlements.count() == 1 and Job.objects.get().status == "queued"


# --- the site's own address, for the link ---------------------------------------------------


def test_the_servers_address_for_links_is_its_first_allowed_host(monkeypatch):
    for name, value in {
        "SECRET_KEY": "x" * 50,
        "DATABASE_URL": "postgres://u:p@localhost:5432/db",
        "ALLOWED_HOSTS": "app.example.org,other.example.org",
        "EMAIL_HOST": "smtp.example.com",
        "EMAIL_HOST_USER": "u",
        "EMAIL_HOST_PASSWORD": "p",
        "DEFAULT_FROM_EMAIL": "noreply@example.org",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SITE_URL", raising=False)
    from config.settings import base, production

    try:
        importlib.reload(base)
        assert importlib.reload(production).SITE_URL == "https://app.example.org"
        monkeypatch.setenv("SITE_URL", "https://survey.example.org")
        importlib.reload(base)
        assert importlib.reload(production).SITE_URL == "https://survey.example.org"
    finally:
        monkeypatch.undo()
        importlib.reload(base)
