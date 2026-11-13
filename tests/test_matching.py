"""
Milestone 5, PR 4: possible duplicates, and linking two logins.

The rules. When two accounts look like the same person (the same phone number,
or the same full name when each belongs to an organization), nothing happens
to either: the pair is stored as a "possible duplicate" for a superuser.
Neither person is told. The superuser says "same person", which links the two
logins so they share their personal licences, or "different people", which
closes the pair for good. A link can be undone. Only superusers see any of it.

A survey is a "possible repeat" when the person said they had taken it
before, or the same person (this login or one linked to it) has an earlier
submitted survey. A pair nobody has decided marks nothing.
"""

import importlib
import json

import pytest
from allauth.account.models import EmailAddress
from django.apps import apps as django_apps
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.accounts.models import Account, ContactPoint, Person
from apps.audit.models import AuditLog
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.jobs import services as jobs
from apps.jobs.models import Job
from apps.matching import rules, services
from apps.matching.models import MatchCandidate
from apps.responses import services as surveys
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME

from . import payments
from .orgs import add_member, make_enterprise, org_with_admin, run_together
from .test_response_context import published_survey
from .test_response_services import finish_pages
from .test_verification import fake_request, verify

PASSWORD = "correct horse battery staple"
PHONE = "+919876543210"
OTHER_PHONE = "+919876543211"
THIRD_PHONE = "+919876543212"


def someone(email, phone, name=""):
    """A signed-up account with a verified email, this phone and this name."""
    account = accounts.register(email, phone, None, PASSWORD, full_name=name)
    ContactPoint.objects.filter(account=account, kind="email").update(verified_at=timezone.now())
    EmailAddress.objects.filter(user=account).update(verified=True)
    return account


@pytest.fixture
def ann(db):
    """The older of two accounts that share a phone number."""
    return someone("ann@example.com", PHONE)


@pytest.fixture
def ann2(ann):
    """The newer one: the same person at another address, perhaps."""
    return someone("ann.other@example.com", PHONE)


@pytest.fixture
def pair(ann, ann2):
    """The two as a possible duplicate, waiting for a decision."""
    (candidate,) = services.run_for_account(ann2)
    return candidate


@pytest.fixture
def root(client, db):
    account = Account.objects.create_superuser("root@example.com", PASSWORD)
    client.force_login(account)
    return account


@pytest.fixture
def support(client, db):
    account = Account.objects.create_user("support@example.com", PASSWORD)
    account.is_staff = True
    account.save()
    account.groups.add(Group.objects.get(name=GROUP_NAME))
    client.force_login(account)
    return account


def fresh(thing):
    return type(thing).objects.get(pk=thing.pk)


def refusal(action):
    with pytest.raises(services.Refused) as caught:
        action()
    return str(caught.value)


def give(account, tier=1):
    """Staff give this login a personal licence."""
    account = fresh(account)  # the fixture's copy may predate a link
    return licences.grant_individual(account.person, tier, "manual", granted_to=account)


def take(account, membership=None, took_before=False):
    """The account takes the whole survey, the real way, and submits it."""
    response = surveys.start_response(fresh(account), membership)
    response = surveys.save_self_report(response, took_before, "other" if took_before else "")
    return surveys.submit(finish_pages(response, surveys.page_count(response)))


def people():
    """Which person each account belongs to."""
    return dict(Account.objects.values_list("pk", "person_id"))


def audit_row(action):
    (row,) = AuditLog.objects.filter(action=action)
    return row


# --- looking ----------------------------------------------------------------------------------


@pytest.mark.django_db
class TestSamePhone:
    def test_two_accounts_with_one_phone_number_are_a_possible_duplicate(self, ann, ann2):
        (candidate,) = services.run_for_account(ann2)
        assert (candidate.account_a, candidate.account_b) == (ann, ann2)
        assert candidate.status == "flagged" and candidate.signals == ["same_phone"]
        assert candidate.resolved_by is None and candidate.resolved_at is None

    def test_the_pair_is_stored_once_however_often_and_from_whichever_side(self, ann, ann2):
        for account in (ann, ann2, ann, ann2):
            services.run_for_account(account)
        only = MatchCandidate.objects.get()
        assert (only.account_a, only.account_b) == (ann, ann2)

    def test_different_numbers_are_nothing(self, ann):
        someone("bea@example.com", OTHER_PHONE)
        assert services.run_for_account(ann) == [] and not MatchCandidate.objects.exists()

    def test_a_number_changed_to_someone_elses_is_found(self, ann):
        bea = someone("bea@example.com", OTHER_PHONE)
        accounts.change_phone(bea, PHONE, None)
        assert len(services.run_for_account(bea)) == 1

    def test_three_accounts_with_one_number_are_three_pairs(self, ann, ann2):
        third = someone("ann.third@example.com", PHONE)
        assert len(services.run_for_account(third)) == 2
        services.run_for_account(ann)
        assert MatchCandidate.objects.count() == 3

    def test_an_erased_or_switched_off_account_is_never_part_of_a_pair(self, ann, ann2):
        Account.objects.filter(pk=ann2.pk).update(is_active=False)
        assert services.run_for_account(ann) == [] and services.run_for_account(ann2) == []
        Account.objects.filter(pk=ann2.pk).update(is_active=True, anonymised_at=timezone.now())
        assert services.run_for_account(ann) == [] and services.run_for_account(ann2) == []

    def test_the_pair_holds_the_name_of_the_rule_and_never_the_number(self, pair):
        stored = json.dumps([pair.signals, str(pair)])
        assert "987654" not in stored and "@" not in stored and "ann" not in stored


@pytest.mark.django_db
class TestSameName:
    def members(self, first="Ann Lee", second="Ann Lee", same_organization=False):
        one = someone("ann@example.com", PHONE, first)
        two = someone("ann.other@example.com", OTHER_PHONE, second)
        acme = make_enterprise("Acme")
        add_member(acme, one)
        add_member(acme if same_organization else make_enterprise("Bolt"), two)
        return one, two

    def test_the_same_name_in_two_organizations_is_a_possible_duplicate(self, db):
        one, two = self.members()
        (candidate,) = services.run_for_account(two)
        assert (candidate.account_a, candidate.account_b) == (one, two)
        assert candidate.signals == ["same_name"]

    def test_and_in_one_organization(self, db):
        _, two = self.members(same_organization=True)
        assert len(services.run_for_account(two)) == 1

    def test_capitals_accents_and_spaces_do_not_matter(self, db):
        _, two = self.members("José  GARCÍA", "jose garcia")
        assert len(services.run_for_account(two)) == 1

    def test_a_different_name_is_nothing_and_there_is_no_close_enough(self, db):
        _, two = self.members("Ann Lee", "Anne Lee")
        assert services.run_for_account(two) == []

    def test_two_strangers_who_share_a_name_are_nothing(self, db):
        one = someone("ann@example.com", PHONE, "Ann Lee")
        two = someone("ann.other@example.com", OTHER_PHONE, "Ann Lee")
        assert services.run_for_account(two) == []
        add_member(make_enterprise("Acme"), one)  # one member, one stranger: still nothing
        assert services.run_for_account(two) == [] and services.run_for_account(one) == []

    def test_someone_who_has_left_their_organization_still_counts(self, db):
        """The usual story: they left one employer and were invited by the next."""
        one = someone("ann@example.com", PHONE, "Ann Lee")
        two = someone("ann.other@example.com", OTHER_PHONE, "Ann Lee")
        add_member(make_enterprise("Acme"), one, active=False)
        add_member(make_enterprise("Bolt"), two)
        assert len(services.run_for_account(two)) == 1

    def test_accounts_with_no_name_never_match_each_other(self, db):
        _, two = self.members("", "")
        assert services.run_for_account(two) == []

    def test_what_a_name_is_compared_as(self):
        assert rules.name_key("  José   GARCÍA ") == "jose garcia"
        assert rules.name_key("Straße") == rules.name_key("STRASSE")
        assert rules.name_key(None) == ""

    def test_a_pair_found_by_both_rules_says_both(self, db):
        one = someone("ann@example.com", PHONE, "Ann Lee")
        two = someone("ann.other@example.com", PHONE, "Ann Lee")
        (first,) = services.run_for_account(two)
        assert first.signals == ["same_phone"]
        add_member(make_enterprise("Acme"), one)
        add_member(make_enterprise("Bolt"), two)
        (again,) = services.run_for_account(one)
        assert again.pk == first.pk and again.signals == ["same_name", "same_phone"]

    def test_what_an_undecided_pair_had_in_common_before_is_kept(self, db):
        """They shared a phone when first found; one has since changed it, and now a name matches."""
        one = someone("ann@example.com", PHONE, "Ann Lee")
        two = someone("ann.other@example.com", PHONE, "Ann Lee")
        services.run_for_account(two)
        accounts.change_phone(two, OTHER_PHONE, None)
        add_member(make_enterprise("Acme"), one)
        add_member(make_enterprise("Bolt"), two)
        (again,) = services.run_for_account(two)
        assert again.signals == ["same_name", "same_phone"]


@pytest.mark.django_db
class TestLookingChangesNothing:
    def test_no_rule_changes_any_accounts_person(self, db):
        one = someone("ann@example.com", PHONE, "Ann Lee")
        two = someone("ann.other@example.com", PHONE, "Ann Lee")
        add_member(make_enterprise("Acme"), one)
        add_member(make_enterprise("Bolt"), two)
        give(one)
        before, licences_before = people(), list(Entitlement.objects.values("pk", "person_id"))
        for _, _, rule in rules.RULES:
            rule(one), rule(two)
        services.run_for_account(one), services.run_for_account(two)
        assert MatchCandidate.objects.count() == 1
        assert people() == before
        assert list(Entitlement.objects.values("pk", "person_id")) == licences_before
        assert not Person.objects.filter(merged_into__isnull=False).exists()

    def test_a_pair_already_decided_is_left_exactly_as_it_is(self, pair, root):
        services.reject(pair, root)
        decided_at = fresh(pair).resolved_at
        assert services.run_for_account(pair.account_a) == []
        assert services.run_for_account(pair.account_b) == []
        again = MatchCandidate.objects.get()
        assert again.status == "rejected" and again.resolved_at == decided_at

    def test_two_logins_already_linked_are_not_raised_again(self, pair, root):
        services.confirm(pair, root)
        assert services.run_for_account(pair.account_a) == []
        assert MatchCandidate.objects.get().status == "confirmed"

    def test_a_link_that_was_undone_is_not_raised_again_either(self, pair, root):
        services.confirm(pair, root)
        services.unlink(pair, root)
        assert services.run_for_account(pair.account_b) == []
        assert MatchCandidate.objects.get().status == "unlinked"


# --- when the look happens --------------------------------------------------------------------


def queued(account):
    return Job.objects.filter(kind=accounts.LOOK_FOR_DUPLICATES, payload={"account_id": account.pk})


@pytest.mark.django_db
class TestWhenTheLookHappens:
    def test_the_job_finds_the_pair_and_holds_only_a_number(self, ann, ann2):
        accounts.look_for_duplicates_later(ann2)
        assert queued(ann2).count() == 1 and not MatchCandidate.objects.exists()
        jobs.run_due()
        assert MatchCandidate.objects.count() == 1
        assert queued(ann2).get().status == "done"

    def test_run_twice_by_the_worker_it_is_still_one_pair(self, ann, ann2):
        accounts.look_for_duplicates_later(ann2)
        accounts.look_for_duplicates_later(ann2)
        jobs.run_due()
        assert MatchCandidate.objects.count() == 1

    def test_a_job_for_an_account_that_has_gone_does_nothing(self, db):
        jobs.enqueue(accounts.LOOK_FOR_DUPLICATES, {"account_id": 999_999})
        jobs.run_due()
        assert Job.objects.get().status == "done" and not MatchCandidate.objects.exists()

    def test_verifying_an_email_queues_a_look(self, client, db):
        ann = accounts.register("ann@example.com", PHONE, None, PASSWORD)
        assert not queued(ann).exists()
        verify(client, ann, "ann@example.com")
        assert queued(ann).count() == 1

    def test_changing_a_phone_or_a_name_queues_a_look(self, ann):
        accounts.change_phone(ann, PHONE, None)  # the same number: nothing changed
        assert not queued(ann).exists()
        accounts.change_phone(ann, OTHER_PHONE, None)
        accounts.set_full_name(ann, "Ann Lee")
        assert queued(ann).count() == 2

    def test_joining_an_organization_queues_a_look(self, ann):
        _, admin = org_with_admin("Acme")
        orgs.redeem_code(orgs.create_code(admin, 5).code, ann)
        invite, _ = orgs.invite_by_email(admin, "ann.other@example.com")
        ann2 = someone("ann.other@example.com", OTHER_PHONE)
        orgs.accept_invite(invite.token, ann2)
        assert queued(ann).count() == 1 and queued(ann2).count() == 1

    def test_submitting_a_survey_queues_a_look(self, ann):
        give(ann)
        take(ann)
        assert queued(ann).count() == 1

    def test_end_to_end_two_sign_ups_with_one_phone_reach_the_superuser(self, client, db):
        for email in ("ann@example.com", "ann.other@example.com"):
            verify(client, accounts.register(email, PHONE, None, PASSWORD), email)
        jobs.run_due()
        assert MatchCandidate.objects.get().status == "flagged"
        assert (
            people()[MatchCandidate.objects.get().account_a_id]
            != (people()[MatchCandidate.objects.get().account_b_id])
        )


# --- "same person": linking -------------------------------------------------------------------


@pytest.mark.django_db
class TestLinking:
    def test_the_newer_login_moves_onto_the_older_logins_person(self, pair, ann, ann2, root):
        own = ann2.person
        services.confirm(pair, root)
        assert fresh(ann2).person == fresh(ann).person == ann.person
        assert fresh(own).merged_into == ann.person
        linked = fresh(pair)
        assert linked.status == "confirmed" and linked.resolved_by == root
        assert linked.resolved_at is not None and linked.old_person == own

    def test_either_login_can_then_use_the_others_personal_licence(self, pair, ann, ann2, root):
        hers, other = give(ann, 2), give(ann2, 3)
        assert surveys.start_response(ann2).entitlement == other  # before: only her own
        Response.objects.all().delete()
        services.confirm(pair, root)
        assert fresh(other).person == ann.person and fresh(hers).person == ann.person
        first = surveys.start_response(fresh(ann2))
        assert first.entitlement == hers  # the oldest of the shared ones
        assert licences.unused_licence(fresh(ann)) == other

    def test_both_logins_keep_working_and_keep_their_own_surveys(
        self, client, pair, ann, ann2, root
    ):
        give(ann), give(ann2)
        mine = take(ann)
        services.confirm(pair, root)
        theirs = take(ann2)
        assert list(fresh(ann).responses.all()) == [mine]
        assert list(fresh(ann2).responses.all()) == [theirs]
        assert client.login(email="ann@example.com", password=PASSWORD)
        page = client.get(reverse("responses:history")).content.decode()
        assert reverse("responses:result", args=[mine.pk]) in page
        assert reverse("responses:result", args=[theirs.pk]) not in page
        assert client.get(reverse("responses:result", args=[theirs.pk])).status_code == 404
        assert client.login(email="ann.other@example.com", password=PASSWORD)

    def test_memberships_and_their_licences_do_not_move(self, pair, ann, ann2, root):
        enterprise, admin = org_with_admin("Acme")
        orgs.set_seat_pool(enterprise, 2, 1)
        member = add_member(enterprise, ann2)
        seat = licences.assign_seat(admin, member, 2)
        services.confirm(pair, root)
        assert fresh(seat).membership == member and fresh(seat).person is None
        assert not fresh(ann).memberships.exists()
        assert licences.unused_licence(fresh(ann)) is None  # a seat is not a personal licence
        assert licences.unused_licence(fresh(ann), None) is None
        assert licences.unused_licence(fresh(ann2), member) == seat

    def test_it_is_written_in_the_audit_log_in_numbers(self, pair, ann, ann2, root):
        licence = give(ann2)
        services.confirm(pair, root)
        row = audit_row("accounts.linked")
        assert row.actor == root and row.target_id == str(pair.pk)
        assert row.detail == {"kept": ann.pk, "moved": ann2.pk, "licences": [licence.pk]}

    def test_only_a_superuser_can_link(self, pair, ann, support):
        for by in (support, ann, None):
            assert refusal(lambda by=by: services.confirm(pair, by)) == services.SUPERUSERS_ONLY
        Account.objects.filter(pk=support.pk).update(is_superuser=True, is_active=False)
        assert refusal(lambda: services.confirm(pair, fresh(support))) == services.SUPERUSERS_ONLY
        assert fresh(pair).status == "flagged" and people()[pair.account_b_id] != ann.person_id

    def test_an_account_erased_or_switched_off_since_cannot_be_linked(self, pair, ann2, root):
        Account.objects.filter(pk=ann2.pk).update(is_active=False)
        assert refusal(lambda: services.confirm(pair, root)) == services.GONE
        assert services.link_preview(fresh(pair)) == {"can": False, "why_not": services.GONE}

    def test_a_login_already_linked_cannot_be_linked_to_a_third(self, pair, ann, ann2, root):
        third = someone("ann.third@example.com", PHONE)
        services.run_for_account(third)
        services.confirm(pair, root)
        for older in (ann, ann2):
            other = MatchCandidate.objects.get(account_a=older, account_b=third)
            said = refusal(lambda other=other: services.confirm(other, root))
            assert f"Account #{older.pk} is already linked" in said
            assert services.link_preview(other)["can"] is False
        assert fresh(third).person == third.person

    def test_a_pair_decided_as_different_cannot_then_be_linked(self, pair, root):
        services.reject(pair, root)
        assert refusal(lambda: services.confirm(pair, root)) == services.NOT_WAITING
        assert refusal(lambda: services.reject(pair, root)) == services.NOT_WAITING

    def test_linking_twice_is_refused_the_second_time(self, pair, root):
        services.confirm(pair, root)
        assert refusal(lambda: services.confirm(pair, root)) == services.NOT_WAITING
        assert AuditLog.objects.filter(action="accounts.linked").count() == 1

    def test_the_page_is_told_what_linking_will_do(self, pair, ann, ann2):
        give(ann2), give(ann2), give(ann)
        preview = services.link_preview(pair)
        assert preview == {"can": True, "kept": ann, "moved": ann2, "licences": 2}
        assert people()[ann2.pk] != ann.person_id  # asking changed nothing


@pytest.mark.django_db(transaction=True)
def test_two_superusers_deciding_at_the_same_moment_link_them_once():
    """Two requests in two threads, as two browser tabs would be: one wins, one is refused."""
    root = Account.objects.create_superuser("root@example.com", PASSWORD)
    ann = someone("ann@example.com", PHONE)
    ann2 = someone("ann.other@example.com", PHONE)
    licence = licences.grant_individual(ann2.person, 1, "manual")
    (candidate,) = services.run_for_account(ann2)
    first, second = run_together(
        lambda: services.confirm(candidate, root), lambda: services.reject(candidate, root)
    )
    refused = [result for result in (first, second) if isinstance(result, services.Refused)]
    assert len(refused) == 1 and str(refused[0]) == services.NOT_WAITING
    decided = fresh(candidate)
    assert AuditLog.objects.filter(target_id=str(candidate.pk)).count() == 1
    if decided.status == "confirmed":
        assert fresh(ann2).person == ann.person and fresh(licence).person == ann.person
    else:
        assert decided.status == "rejected" and fresh(ann2).person != ann.person


@pytest.mark.django_db(transaction=True)
def test_starting_a_survey_while_being_linked_ends_with_one_person_and_one_attempt():
    """The login being moved starts its survey at the very moment it is linked."""
    published_survey()
    root = Account.objects.create_superuser("root@example.com", PASSWORD)
    ann = someone("ann@example.com", PHONE)
    ann2 = someone("ann.other@example.com", PHONE)
    licence = licences.grant_individual(ann2.person, 1, "manual")
    (candidate,) = services.run_for_account(ann2)
    linked, started = run_together(
        lambda: services.confirm(candidate, root), lambda: surveys.start_response(ann2)
    )
    assert not isinstance(linked, Exception) and not isinstance(started, Exception)
    assert fresh(ann2).person == ann.person and fresh(licence).person == ann.person
    assert Response.objects.get().entitlement == licence


@pytest.mark.django_db
class TestDifferentPeople:
    def test_the_pair_is_closed_and_nothing_else_changes(self, pair, ann, ann2, root):
        before = people()
        services.reject(pair, root)
        closed = fresh(pair)
        assert closed.status == "rejected" and closed.resolved_by == root
        assert people() == before
        row = audit_row("possible_duplicate.rejected")
        assert row.actor == root and row.target_id == str(pair.pk) and row.detail == {}

    def test_only_a_superuser_can_say_so(self, pair, support):
        assert refusal(lambda: services.reject(pair, support)) == services.SUPERUSERS_ONLY
        assert fresh(pair).status == "flagged"


# --- undoing a link ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUndoingALink:
    def test_the_newer_login_gets_its_own_person_back(self, pair, ann, ann2, root):
        own = ann2.person
        services.confirm(pair, root)
        services.unlink(pair, root)
        assert fresh(ann2).person == own and fresh(ann).person == ann.person
        assert fresh(own).merged_into is None
        undone = fresh(pair)
        assert undone.status == "unlinked" and undone.resolved_by == root

    def test_each_login_gets_back_the_unused_licences_that_were_its_own(
        self, pair, ann, ann2, root
    ):
        hers, other = give(ann), give(ann2)
        services.confirm(pair, root)
        services.unlink(pair, root)
        assert fresh(hers).person == fresh(ann).person
        assert fresh(other).person == fresh(ann2).person
        assert licences.unused_licence(fresh(ann)) == hers
        assert licences.unused_licence(fresh(ann2)) == other

    def test_a_licence_given_or_bought_while_linked_goes_to_the_login_it_was_for(
        self, pair, ann, ann2, root, monkeypatch, settings
    ):
        services.confirm(pair, root)
        stripe = payments.install(monkeypatch, settings)
        from apps.payments import services as buying

        buying.start_personal(fresh(ann2), 2, request=fake_request())
        bought = buying.fulfil(stripe.pay()).entitlement
        given_newer, given_older = give(ann2), give(ann)
        assert bought.granted_to == ann2 and bought.person == ann.person
        services.unlink(pair, root)
        own = fresh(ann2).person
        assert fresh(bought).person == own and fresh(given_newer).person == own
        assert fresh(given_older).person == ann.person

    def test_a_licence_follows_the_login_that_used_it(self, pair, ann, ann2, root):
        """Whoever it was first given to: that login's survey is on it."""
        hers, other = give(ann), give(ann2)
        services.confirm(pair, root)
        used_by_newer = take(ann2)  # the oldest shared licence: the older login's
        used_by_older = take(ann)  # the one left: the newer login's
        assert (used_by_newer.entitlement, used_by_older.entitlement) == (hers, other)
        services.unlink(pair, root)
        assert fresh(hers).person == fresh(ann2).person
        assert fresh(other).person == fresh(ann).person

    def test_the_page_is_told_what_undoing_will_do(self, pair, ann, ann2, root):
        give(ann), give(ann2), give(ann2)
        assert services.unlink_preview(pair) == {"can": False, "why_not": services.NOT_LINKED}
        services.confirm(pair, root)
        preview = services.unlink_preview(fresh(pair))
        assert preview == {"can": True, "kept": ann, "moved": ann2, "going": 2, "staying": 1}
        assert fresh(ann2).person == ann.person  # asking changed nothing

    def test_it_is_written_in_the_audit_log_in_numbers(self, pair, ann, ann2, root):
        licence = give(ann2)
        services.confirm(pair, root)
        services.unlink(pair, root)
        row = audit_row("accounts.unlinked")
        assert row.actor == root
        assert row.detail == {"kept": ann.pk, "moved": ann2.pk, "licences": [licence.pk]}

    def test_only_a_link_can_be_undone_and_only_by_a_superuser(self, pair, support, root):
        assert refusal(lambda: services.unlink(pair, root)) == services.NOT_LINKED
        services.confirm(pair, root)
        assert refusal(lambda: services.unlink(pair, support)) == services.SUPERUSERS_ONLY
        services.unlink(pair, root)
        assert refusal(lambda: services.unlink(pair, root)) == services.NOT_LINKED

    def test_they_can_be_linked_again_afterwards(self, pair, ann, ann2, root):
        other = give(ann2)
        services.confirm(pair, root)
        services.unlink(pair, root)
        services.confirm(pair, root)
        assert fresh(pair).status == "confirmed"
        assert fresh(ann2).person == ann.person and fresh(other).person == ann.person
        services.unlink(pair, root)
        assert fresh(other).person == fresh(ann2).person != ann.person

    def test_if_the_old_person_row_has_gone_a_new_one_is_made(self, pair, ann, ann2, root):
        services.confirm(pair, root)
        Person.objects.filter(pk=ann2.person_id).delete()
        services.unlink(fresh(pair), root)
        own = fresh(ann2).person
        assert own is not None and own != ann.person and own.accounts.count() == 1


# --- erasing ----------------------------------------------------------------------------------


@pytest.mark.django_db
class TestErasing:
    def test_an_account_deleted_outright_takes_its_pairs_with_it(self, pair, ann2):
        assert erasure.erase_account(ann2).action == erasure.DELETE
        assert not MatchCandidate.objects.exists()

    def test_an_account_stripped_and_kept_loses_its_pairs_too(self, pair, ann):
        give(ann)
        take(ann)
        assert erasure.erase_account(ann).action == erasure.ANONYMISE
        assert not MatchCandidate.objects.exists()

    def test_whichever_of_the_two_is_stripped(self, pair, ann2):
        give(ann2)
        take(ann2)
        assert erasure.erase_account(ann2).action == erasure.ANONYMISE
        assert not MatchCandidate.objects.exists()

    def test_erasing_one_linked_login_leaves_the_other_its_own_licences(
        self, pair, ann, ann2, root
    ):
        """The survey is kept, so the login is stripped; only its own unused licences go."""
        give(ann)
        take(ann)
        hers_unused, other_unused = give(ann), give(ann2)
        services.confirm(pair, root)
        assert erasure.erase_account(fresh(ann)).action == erasure.ANONYMISE
        assert fresh(hers_unused).revoked_at is not None
        assert fresh(other_unused).revoked_at is None
        assert licences.unused_licence(fresh(ann2)) == other_unused

    def test_deleting_one_linked_login_leaves_the_other_working(self, pair, ann, ann2, root):
        other = give(ann2)
        services.confirm(pair, root)
        assert erasure.erase_account(fresh(ann)).action == erasure.DELETE
        assert licences.unused_licence(fresh(ann2)) == other
        assert surveys.start_response(fresh(ann2)).entitlement == other

    def test_an_account_with_no_other_login_still_loses_all_its_unused_licences(self, ann):
        give(ann)
        take(ann)
        unused = give(ann)
        Entitlement.objects.filter(pk=unused.pk).update(granted_to=None)  # an old licence
        erasure.erase_account(ann)
        assert fresh(unused).revoked_at is not None


# --- whose a personal licence is --------------------------------------------------------------


@pytest.mark.django_db
class TestGrantedTo:
    def test_a_licence_for_a_person_with_one_login_is_that_logins(self, ann):
        assert licences.grant_individual(ann.person, 1, "manual").granted_to == ann

    def test_with_two_linked_logins_it_is_the_one_named(self, pair, ann, ann2, root):
        services.confirm(pair, root)
        person = fresh(ann).person
        newer = fresh(ann2)
        assert licences.grant_individual(person, 1, "manual", granted_to=newer).granted_to == ann2
        assert licences.grant_individual(person, 1, "manual").granted_to is None

    def test_a_login_of_another_person_is_refused(self, ann, ann2):
        with pytest.raises(Exception, match="does not belong"):
            licences.grant_individual(ann.person, 1, "manual", granted_to=ann2)

    def test_staff_granting_in_the_admin_record_the_login_they_chose(
        self, client, pair, ann, ann2, root
    ):
        services.confirm(pair, root)  # one person, two logins: the choice now matters
        client.post(
            reverse("admin:entitlements_entitlement_add"),
            {"account": ann2.pk, "tier": 2, "source": "manual"},
        )
        licence = Entitlement.objects.get()
        assert licence.granted_to == ann2 and licence.person == ann.person

    def test_a_licence_for_a_membership_has_none(self, ann):
        member = add_member(make_enterprise("Acme"), ann)
        assert licences.grant_for_membership(member, 1, "manual").granted_to is None

    def test_licences_from_before_this_existed_were_filled_in(self, ann):
        licence = give(ann)
        seat = licences.grant_for_membership(add_member(make_enterprise("Acme"), ann), 1, "manual")
        Entitlement.objects.update(granted_to=None)
        migration = importlib.import_module("apps.entitlements.migrations.0004_granted_to")
        migration.fill_granted_to(django_apps, None)
        assert fresh(licence).granted_to == ann and fresh(seat).granted_to is None


# --- possible repeat --------------------------------------------------------------------------


@pytest.mark.django_db
class TestPossibleRepeat:
    def test_a_first_survey_is_not_one(self, ann):
        give(ann)
        assert take(ann).possible_repeat is False

    def test_saying_you_took_it_before_makes_it_one(self, ann):
        give(ann)
        assert take(ann, took_before=True).possible_repeat is True

    def test_a_second_survey_from_the_same_login_is_one(self, ann):
        give(ann), give(ann)
        first, second = take(ann), take(ann)
        assert (fresh(first).possible_repeat, second.possible_repeat) == (False, True)

    def test_a_survey_from_a_linked_login_is_one(self, pair, ann, ann2, root):
        give(ann), give(ann2)
        services.confirm(pair, root)
        first, second = take(ann), take(ann2)
        assert (fresh(first).possible_repeat, second.possible_repeat) == (False, True)

    def test_a_pair_nobody_has_decided_marks_nothing(self, pair, ann, ann2):
        give(ann), give(ann2)
        assert take(ann).possible_repeat is False and take(ann2).possible_repeat is False

    def test_linking_marks_the_later_of_two_surveys_already_taken(self, pair, ann, ann2, root):
        give(ann), give(ann2)
        earlier, later = take(ann2), take(ann)  # the newer login happened to go first
        services.confirm(pair, root)
        assert (fresh(earlier).possible_repeat, fresh(later).possible_repeat) == (False, True)

    def test_undoing_the_link_takes_the_mark_off_again(self, pair, ann, ann2, root):
        give(ann), give(ann2), give(ann2)
        take(ann)
        later, said_so = take(ann2), take(ann2, took_before=True)
        services.confirm(pair, root)
        assert fresh(later).possible_repeat is True
        services.unlink(pair, root)
        assert fresh(later).possible_repeat is False
        assert fresh(said_so).possible_repeat is True  # their own earlier one, and they said so

    def test_an_organizations_admin_sees_the_mark_and_nothing_about_the_other_login(
        self, client, pair, ann, ann2, root
    ):
        give(ann)
        take(ann)  # personally, on the older login
        enterprise, admin = org_with_admin("Acme")
        orgs.set_seat_pool(enterprise, 2, 1)
        member = add_member(enterprise, ann2)
        licences.assign_seat(admin, member, 2)
        services.confirm(pair, root)
        response = take(ann2, member)
        assert response.possible_repeat is True
        client.force_login(admin.account)
        table = client.get(reverse("organization_responses", args=[enterprise.slug]))
        page = table.content.decode()
        assert "ossible repeat" in page
        one = client.get(
            reverse("organization_response", args=[enterprise.slug, response.pk])
        ).content.decode()
        assert "it looks as though this person has taken the survey before" in one
        for text in (page, one):
            assert "ann@example.com" not in text and "duplicate" not in text.lower()


# --- the superuser's pages --------------------------------------------------------------------


def list_page():
    return reverse("admin:matching_matchcandidate_changelist")


def detail_page(candidate):
    return reverse("admin:matching_matchcandidate_change", args=[candidate.pk])


def decide_page(candidate, decision):
    return reverse("admin:matching_matchcandidate_decide", args=[candidate.pk, decision])


@pytest.mark.django_db
class TestAdminPages:
    def test_the_list_puts_those_waiting_first(self, client, pair, root):
        third = someone("cy@example.com", OTHER_PHONE)
        fourth = someone("cy.other@example.com", OTHER_PHONE)
        (decided,) = services.run_for_account(fourth)
        services.reject(decided, root)
        page = client.get(list_page()).content.decode()
        assert page.index(f"accounts {pair.account_a_id} and") < page.index(
            f"accounts {third.pk} and"
        )
        assert "Waiting for a decision" in page and "Different people" in page
        assert "They gave the same phone number." in page

    def test_opening_one_shows_the_two_accounts_side_by_side(self, client, pair, ann, ann2, root):
        accounts.set_full_name(ann, "Ann Lee")
        add_member(make_enterprise("Acme"), ann)
        give(ann2)
        page = client.get(detail_page(pair)).content.decode()
        for expected in (
            "ann@example.com",
            "ann.other@example.com",
            "Ann Lee",
            "Acme (active)",
            "They gave the same phone number.",
            "Personal licences not yet used: 1",
            decide_page(pair, "same"),
            decide_page(pair, "different"),
        ):
            assert expected in page
        assert decide_page(pair, "undo") not in page

    def test_the_page_before_linking_says_what_will_happen_and_changes_nothing(
        self, client, pair, ann2, root
    ):
        give(ann2)
        page = client.get(decide_page(pair, "same")).content.decode()
        assert "Both logins keep working" in page and "Yes, link them" in page
        assert f"Account {ann2.pk} brings 1 with it" in page
        assert fresh(pair).status == "flagged" and not LogEntry.objects.exists()

    def test_same_person_links_them_and_writes_the_history(self, client, pair, ann, ann2, root):
        response = client.post(decide_page(pair, "same"))
        assert response.status_code == 302 and response["Location"] == detail_page(pair)
        assert fresh(ann2).person == ann.person and fresh(pair).status == "confirmed"
        line = LogEntry.objects.get()
        assert line.user == root and "@" not in line.object_repr + line.change_message
        assert line.change_message == (
            f"Linked: account {ann2.pk} now shares one set of personal licences "
            f"with account {ann.pk}"
        )
        page = client.get(detail_page(pair)).content.decode()
        assert decide_page(pair, "undo") in page and decide_page(pair, "same") not in page

    def test_different_people_closes_it(self, client, pair, root):
        page = client.get(decide_page(pair, "different")).content.decode()
        assert "will not be raised again" in page
        client.post(decide_page(pair, "different"))
        assert fresh(pair).status == "rejected"
        assert LogEntry.objects.get().change_message == "Closed as different people"
        after = client.get(detail_page(pair)).content.decode()
        assert "/decide/" not in after

    def test_undo_puts_them_apart_again(self, client, pair, ann, ann2, root):
        give(ann2)
        client.post(decide_page(pair, "same"))
        page = client.get(decide_page(pair, "undo")).content.decode()
        assert f"Account {ann2.pk} leaves with 1 personal licence(s)" in page
        client.post(decide_page(pair, "undo"))
        assert fresh(pair).status == "unlinked" and fresh(ann2).person != ann.person
        assert decide_page(pair, "same") in client.get(detail_page(pair)).content.decode()

    def test_a_decision_that_does_not_fit_is_turned_away(self, client, pair, ann2, root):
        for decision in ("undo", "anything"):
            response = client.post(decide_page(pair, decision), follow=True)
            assert services.NOT_WAITING in response.content.decode()
        assert fresh(pair).status == "flagged" and not LogEntry.objects.exists()

    def test_a_link_that_cannot_be_made_is_explained_instead_of_offered(
        self, client, pair, ann2, root
    ):
        Account.objects.filter(pk=ann2.pk).update(is_active=False)
        page = client.get(decide_page(pair, "same")).content.decode()
        assert services.GONE in page and "Yes, link them" not in page
        client.post(decide_page(pair, "same"))
        assert fresh(pair).status == "flagged"

    def test_nothing_is_edited_added_or_deleted_by_hand(self, client, pair, root):
        assert client.get(reverse("admin:matching_matchcandidate_add")).status_code == 403
        client.post(detail_page(pair), {"status": "confirmed"})
        delete = reverse("admin:matching_matchcandidate_delete", args=[pair.pk])
        assert client.post(delete, {"post": "yes"}).status_code == 403
        assert fresh(pair).status == "flagged"

    def test_support_staff_cannot_see_or_decide_any_of_it(self, client, pair, ann2, support):
        assert client.get(list_page()).status_code == 403
        assert client.get(detail_page(pair)).status_code == 403
        for decision in ("same", "different", "undo"):
            assert client.get(decide_page(pair, decision)).status_code == 403
            assert client.post(decide_page(pair, decision)).status_code == 403
        assert "Possible duplicates" not in client.get(reverse("admin:index")).content.decode()
        assert fresh(pair).status == "flagged" and people()[ann2.pk] == ann2.person_id

    def test_nor_someone_who_is_not_staff(self, client, pair, ann):
        client.force_login(ann)
        assert client.get(list_page()).status_code == 302
        assert client.post(decide_page(pair, "same")).status_code == 302
        assert fresh(pair).status == "flagged"


def test_possible_duplicates_are_on_no_page_of_the_site_itself():
    """The matching app has no pages of its own: only the Django admin shows it."""
    from pathlib import Path

    from django.conf import settings

    app = Path(settings.BASE_DIR) / "apps" / "matching"
    assert not (app / "views.py").exists() and not (app / "urls.py").exists()
    for path in (Path(settings.BASE_DIR) / "templates").rglob("*.html"):
        if "admin" not in path.parts:
            assert "duplicate" not in path.read_text().lower(), path
