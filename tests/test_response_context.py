"""
Milestone 3, PR 6: a survey attempt is personal or for one organization.

The licence decides which: a membership licence starts an attempt only for that
organization and a personal one only personally. One unfinished attempt per
context, so a personal and an organization attempt can be open together.
Deactivating a member deletes their unfinished attempt for the organization
(and nothing else) and blocks its pages; reactivating makes the same licence
usable again. The pages of an attempt are gated by its own context, and the
personal start page never picks up an organization's attempt.
"""

import pytest
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account, Person
from apps.enterprises import services as orgs
from apps.enterprises.models import Enterprise, Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.funnel.models import FunnelEvent
from apps.responses import services
from apps.responses.models import Response
from apps.survey.models import Question, SurveyVersion
from apps.survey.services import current_version

from .orgs import locked_tables, new_member, org_with_admin, run_together
from .test_verification import PASSWORD


@pytest.fixture
def acme(db):
    """(the organization, its admin's membership)"""
    return org_with_admin("Acme")


@pytest.fixture
def member(acme):
    return new_member(acme[0], "bob@example.com")


def grant(membership, tier=2):
    return licences.grant_for_membership(membership, tier, "manual", None)


def grant_personal(account, tier=1):
    return licences.grant_individual(account.person, tier, "manual", None)


def row(account, licence, **extra):
    """A response made directly, to test the database rules without the service."""
    return Response.objects.create(
        account=account,
        survey_version=current_version(),
        entitlement=licence,
        membership=licence.membership,
        **extra,
    )


def finish(response):
    """
    Answer every statement, lock every page and submit, the way the Next button
    does: each page is handed to `complete_page` with its answers, which saves
    and locks them in one step. Nothing is written past the services. Many
    tests need a finished survey, so this is called thousands of times in a
    run; answering one statement per call (`save_answer`) made it about three
    times as slow, and that path has its own tests in test_response_services.py.
    """
    response = services.save_self_report(response, False)
    pages = {}
    for question in Question.objects.filter(survey_version=response.survey_version):
        pages.setdefault(services.page_of(question.position), {})[question.pk] = 3
    for page in sorted(pages):
        response = services.complete_page(response, page, pages[page])
    return services.submit(response)


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def survey_events():
    """How many page-locked and survey-submitted events the funnel holds."""
    kinds = ("page_locked", "survey_submitted")
    return [FunnelEvent.objects.filter(kind=kind).count() for kind in kinds]


@pytest.mark.django_db
def test_finish_leaves_exactly_what_answering_one_statement_at_a_time_leaves(acme):
    """
    `finish` answers a page per call. Hundreds of tests stand on it, so it must
    end in the same place as the slow way a person could also take: one
    statement per call, then Next, then Submit.
    """
    enterprise, _ = acme
    quick, slow = (new_member(enterprise, f"{name}@example.com") for name in ("quick", "slow"))
    grant(quick)
    grant(slow)

    by_page = finish(services.start_response(quick.account, quick))
    after_one = survey_events()

    response = services.save_self_report(services.start_response(slow.account, slow), False)
    questions = Question.objects.filter(survey_version=response.survey_version)
    for question in questions.order_by("position"):
        response = services.save_answer(response, question.pk, 3)
        if question.position % 5 == 0:
            response = services.complete_page(response, question.position // 5)
    one_by_one = services.submit(response)

    assert by_page.answers == one_by_one.answers and len(by_page.answers) == questions.count()
    for field in ("status", "pages_completed", "took_before", "took_before_via"):
        assert getattr(by_page, field) == getattr(one_by_one, field), field
    assert by_page.status == "submitted" and by_page.submitted_at is not None
    assert by_page.pages_completed == services.page_count(by_page)
    assert by_page.possible_repeat == one_by_one.possible_repeat
    # The same events, too: one per page locked and one for the submission.
    assert survey_events() == [count * 2 for count in after_one]
    assert after_one == [services.page_count(by_page), 1]


# --- the database rules --------------------------------------------------------


@pytest.mark.django_db
class TestDatabaseRules:
    def test_a_personal_and_an_organization_draft_can_be_open_together(self, member):
        account = member.account
        row(account, grant_personal(account))
        row(account, grant(member))
        assert Response.objects.filter(account=account, status="draft").count() == 2

    def test_two_personal_drafts_are_refused(self, member):
        account = member.account
        row(account, grant_personal(account))
        with pytest.raises(IntegrityError), transaction.atomic():
            row(account, grant_personal(account))

    def test_two_drafts_for_one_organization_are_refused(self, member):
        row(member.account, grant(member))
        with pytest.raises(IntegrityError), transaction.atomic():
            row(member.account, grant(member))

    def test_a_draft_for_each_of_two_organizations_is_fine(self, member):
        other, _ = org_with_admin("Other")
        elsewhere = Membership.objects.create(enterprise=other, account=member.account)
        row(member.account, grant(member))
        row(member.account, grant(elsewhere))

    def test_a_submitted_response_does_not_block_a_new_draft(self, member):
        row(member.account, grant(member), status="submitted", submitted_at=timezone.now())
        row(member.account, grant(member))

    def test_a_membership_with_a_response_cannot_be_deleted(self, member):
        row(member.account, grant(member))
        with pytest.raises(IntegrityError), transaction.atomic():
            Membership.objects.filter(pk=member.pk).delete()


# --- starting ------------------------------------------------------------------


@pytest.mark.django_db
class TestStartForAnOrganization:
    def test_a_membership_licence_starts_an_attempt_for_that_organization(self, member):
        licence = grant(member, 3)
        response = services.start_response(member.account, member)
        assert response.status == "draft" and response.account == member.account
        assert response.entitlement == licence and response.membership == member

    def test_it_does_not_start_a_personal_attempt(self, member):
        grant(member)
        with pytest.raises(services.NoLicence):
            services.start_response(member.account)
        assert not Response.objects.exists()

    def test_a_personal_licence_does_not_start_an_organization_attempt(self, member):
        personal = grant_personal(member.account)
        with pytest.raises(services.NoLicence, match="for Acme"):
            services.start_response(member.account, member)
        assert not Response.objects.exists()
        assert licences.unused_licence(member.account) == personal  # not consumed

    def test_a_personal_attempt_has_no_membership(self, member):
        grant_personal(member.account)
        assert services.start_response(member.account).membership is None

    def test_both_can_be_open_together_and_each_is_found_again(self, member):
        account = member.account
        grant_personal(account)
        grant(member)
        personal = services.start_response(account)
        for_acme = services.start_response(account, member)
        assert personal.pk != for_acme.pk
        # Asking again finds the draft of that context, and consumes nothing.
        grant_personal(account)
        grant(member)
        assert services.start_response(account) == personal
        assert services.start_response(account, member) == for_acme
        assert Response.objects.count() == 2
        assert FunnelEvent.objects.filter(kind="survey_started").count() == 2

    def test_the_response_always_has_its_licences_context(self, member):
        account = member.account
        grant_personal(account)
        grant(member)
        services.start_response(account)
        services.start_response(account, member)
        for response in Response.objects.select_related("entitlement"):
            assert response.membership_id == response.entitlement.membership_id

    def test_the_oldest_unused_licence_of_the_membership_goes_first(self, member):
        older = grant(member, 1)
        grant(member, 3)
        assert services.start_response(member.account, member).entitlement == older

    def test_after_submitting_a_new_start_needs_another_licence_there(self, member):
        account = member.account
        grant(member)
        finish(services.start_response(account, member))
        grant_personal(account)  # a personal licence is no help
        with pytest.raises(services.NoLicence):
            services.start_response(account, member)
        second = grant(member)
        assert services.start_response(account, member).entitlement == second

    def test_a_licence_for_one_organization_is_no_use_in_another(self, member):
        other, _ = org_with_admin("Other")
        elsewhere = Membership.objects.create(enterprise=other, account=member.account)
        grant(member)
        with pytest.raises(services.NoLicence, match="for Other"):
            services.start_response(member.account, elsewhere)
        assert not Response.objects.exists()

    def test_someone_elses_membership_is_refused(self, acme, member):
        grant(member)
        carol = new_member(acme[0], "carol@example.com").account
        with pytest.raises(services.Refused, match="not a member"):
            services.start_response(carol, member)
        assert not Response.objects.exists()
        assert licences.unused_licence(member.account, member) is not None

    def test_a_deactivated_membership_is_refused(self, acme, member):
        grant(member)
        orgs.deactivate_membership(member, by=acme[1])
        with pytest.raises(services.Refused, match="deactivated"):
            services.start_response(member.account, member)
        assert not Response.objects.exists()

    def test_a_stale_copy_of_the_membership_is_not_trusted(self, acme, member):
        # The page loaded while they were a member; they were deactivated since.
        grant(member)
        orgs.deactivate_membership(fresh(member), by=acme[1])
        assert member.is_active  # the caller's copy still says so
        with pytest.raises(services.Refused):
            services.start_response(member.account, member)

    def test_locks_the_account_the_membership_and_its_licences(self, member):
        grant(member)
        with CaptureQueriesContext(connection) as captured:
            services.start_response(member.account, member)
        locked = locked_tables(captured.captured_queries)
        assert Account._meta.db_table in locked
        assert Membership._meta.db_table in locked
        assert Entitlement._meta.db_table in locked
        # The organization's own row is the admins' lock (invites, roles); a
        # member starting a survey must not queue behind it.
        assert Enterprise._meta.db_table not in locked

    def test_a_personal_start_still_locks_the_person(self, member):
        grant_personal(member.account)
        with CaptureQueriesContext(connection) as captured:
            services.start_response(member.account)
        locked = locked_tables(captured.captured_queries)
        assert Person._meta.db_table in locked and Membership._meta.db_table not in locked

    def test_a_refused_start_records_nothing(self, acme, member):
        count = FunnelEvent.objects.count()
        with pytest.raises(services.NoLicence):
            services.start_response(member.account, member)
        assert FunnelEvent.objects.count() == count


# --- deactivating --------------------------------------------------------------


@pytest.mark.django_db
class TestDeactivating:
    def test_deletes_the_unfinished_attempt_for_the_organization(self, acme, member):
        licence = grant(member)
        draft = services.save_self_report(services.start_response(member.account, member), False)
        done = orgs.deactivate_membership(member, by=acme[1])
        assert done.draft_deleted
        assert not Response.objects.filter(pk=draft.pk).exists()
        # The licence stays with the membership, unused again, but cannot be used.
        licence.refresh_from_db()
        assert licence.is_active and licence.membership == member
        assert not licences.has_survey_access(member.account, fresh(member))

    def test_keeps_the_personal_attempt_and_everything_submitted(self, acme, member):
        account = member.account
        grant_personal(account)
        personal = services.start_response(account)
        grant(member)
        submitted = finish(services.start_response(account, member))
        grant(member)
        services.start_response(account, member)

        done = orgs.deactivate_membership(member, by=acme[1])

        assert done.draft_deleted
        left = set(Response.objects.values_list("pk", flat=True))
        assert left == {personal.pk, submitted.pk}
        assert fresh(submitted).membership == member  # the organization still has it
        assert services.start_response(account) == personal  # and theirs carries on

    def test_leaves_their_attempt_for_another_organization_alone(self, acme, member):
        other, _ = org_with_admin("Other")
        elsewhere = Membership.objects.create(enterprise=other, account=member.account)
        grant(elsewhere)
        theirs = services.start_response(member.account, elsewhere)
        grant(member)
        services.start_response(member.account, member)
        orgs.deactivate_membership(member, by=acme[1])
        assert list(Response.objects.all()) == [theirs]

    def test_leaves_other_members_attempts_alone(self, acme, member):
        carol = new_member(acme[0], "carol@example.com")
        grant(carol)
        hers = services.start_response(carol.account, carol)
        orgs.deactivate_membership(member, by=acme[1])
        assert list(Response.objects.all()) == [hers]

    def test_says_when_nothing_was_deleted(self, acme, member):
        grant(member)
        assert not orgs.deactivate_membership(member, by=acme[1]).draft_deleted
        # Already deactivated: nothing happens and nothing is reported.
        assert not orgs.deactivate_membership(member, by=acme[1]).draft_deleted

    def test_staff_deactivating_deletes_it_too(self, member):
        grant(member)
        services.start_response(member.account, member)
        assert orgs.deactivate_membership(member).draft_deleted
        assert not Response.objects.exists()

    def test_reactivating_makes_the_same_licence_usable_again(self, acme, member):
        licence = grant(member)
        first = services.start_response(member.account, member)
        orgs.deactivate_membership(member, by=acme[1])
        back = orgs.reactivate_membership(member, by=acme[1])
        again = services.start_response(member.account, back)
        assert again.pk != first.pk and again.entitlement == licence
        assert again.answers == {} and again.took_before is None  # a fresh attempt


# --- two things at once --------------------------------------------------------


def published_survey():
    """A survey to start. An earlier threaded test may have emptied every table."""
    if current_version() is None:
        SurveyVersion.objects.create(number=1, published_at=timezone.now(), question_count=0)


@pytest.mark.django_db(transaction=True)
def test_two_starts_at_once_give_one_attempt_on_one_licence():
    published_survey()
    enterprise, _ = org_with_admin("Acme")
    member = new_member(enterprise, "bob@example.com")
    grant(member)
    grant(member)

    results = run_together(
        lambda: services.start_response(member.account, member),
        lambda: services.start_response(member.account, member),
    )

    assert [type(result) for result in results] == [Response, Response]
    assert results[0].pk == results[1].pk
    assert Response.objects.count() == 1
    assert Entitlement.objects.filter(response__isnull=True).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_start_and_a_deactivation_at_once_leave_no_attempt_behind():
    published_survey()
    enterprise, admin = org_with_admin("Acme")
    member = new_member(enterprise, "bob@example.com")
    grant(member)

    started, deactivated = run_together(
        lambda: services.start_response(member.account, member),
        lambda: orgs.deactivate_membership(member, by=admin),
    )

    # Whichever went first, the member is out and no draft survives: either the
    # start was refused, or the deactivation waited for it and deleted its draft.
    assert isinstance(deactivated, Membership) and not deactivated.is_active
    assert isinstance(started, (Response, services.Refused))
    assert not Response.objects.exists()
    assert Entitlement.objects.get().is_active


# --- the pages of an attempt ---------------------------------------------------


def url(name, response, *args):
    return reverse(f"responses:{name}", args=[response.pk, *args])


@pytest.fixture
def org_draft(client, member):
    """Bob's unfinished attempt for Acme, self-report answered, with Bob logged in."""
    grant(member)
    client.force_login(member.account)
    return services.save_self_report(services.start_response(member.account, member), False)


@pytest.mark.django_db
class TestPages:
    def test_an_organization_attempt_needs_no_personal_licence(self, client, org_draft):
        assert not licences.has_survey_access(org_draft.account)
        assert client.get(url("resume", org_draft)).url == url("page", org_draft, 1)
        assert client.get(url("page", org_draft, 1)).status_code == 200

    def test_answers_can_be_saved_on_it(self, client, org_draft):
        question = Question.objects.filter(survey_version=org_draft.survey_version).get(position=1)
        data = {"question": str(question.pk), f"answer-{question.pk}": "3"}
        assert client.post(url("save_answer", org_draft), data).status_code == 200
        assert fresh(org_draft).answers == {str(question.pk): 3}

    def test_deactivating_blocks_its_pages(self, client, acme, member, org_draft):
        orgs.deactivate_membership(member, by=acme[1])
        for name, args in (("resume", ()), ("page", (1,)), ("review", ())):
            response = client.get(url(name, org_draft, *args))
            # The draft is gone; with no personal licence they land on the start page.
            assert response.status_code == 302 and response.url == reverse("responses:start")
        assert client.post(url("next_page", org_draft), {"page": "1"}).status_code == 302
        assert not Response.objects.exists()

    def test_a_draft_that_outlived_its_membership_is_not_found(self, client, member, org_draft):
        # deactivate_membership deletes the draft; this is the second lock if one
        # ever survives. A personal licence must not open it either.
        grant_personal(member.account)
        Membership.objects.filter(pk=member.pk).update(
            status="deactivated", deactivated_at=timezone.now()
        )
        for name, args in (("resume", ()), ("page", (1,)), ("review", ())):
            assert client.get(url(name, org_draft, *args)).status_code == 404
        assert client.post(url("next_page", org_draft), {"page": "1"}).status_code == 404
        assert fresh(org_draft).pages_completed == 0

    def test_a_draft_on_a_revoked_membership_licence_is_not_found(self, client, member, org_draft):
        Entitlement.objects.filter(pk=org_draft.entitlement_id).update(revoked_at=timezone.now())
        grant(member)  # another licence does not open the old draft
        assert client.get(url("page", org_draft, 1)).status_code == 404

    def test_someone_elses_organization_attempt_cannot_be_opened(self, client, acme, org_draft):
        carol = new_member(acme[0], "carol@example.com")
        grant(carol)
        services.start_response(carol.account, carol)
        client.force_login(carol.account)
        # As for any id that is not hers: the start page without a personal
        # licence, "not found" with one. Her own attempt for Acme opens neither.
        assert client.get(url("page", org_draft, 1)).url == reverse("responses:start")
        grant_personal(carol.account)
        assert client.get(url("page", org_draft, 1)).status_code == 404
        # Not even the organization's admin can open a member's attempt.
        grant_personal(acme[1].account)
        client.force_login(acme[1].account)
        assert client.get(url("page", org_draft, 1)).status_code == 404
        assert client.post(url("next_page", org_draft), {"page": "1"}).status_code == 404
        assert fresh(org_draft).pages_completed == 0

    def test_a_submitted_organization_attempt_goes_to_its_result(self, client, org_draft):
        done = finish(org_draft)
        assert client.get(url("resume", done)).url == url("result", done)
        assert client.get(url("result", done)).status_code == 200

    def test_the_result_outlives_the_membership(self, client, acme, member, org_draft):
        done = finish(org_draft)
        orgs.deactivate_membership(member, by=acme[1])
        assert client.get(url("result", done)).status_code == 200


@pytest.mark.django_db
class TestThePersonalStartPage:
    START = "/survey/start/"

    def test_an_organization_attempt_is_not_personal_access(self, client, org_draft):
        page = client.get(self.START)
        assert page.context["state"] == "no_licence"

    def test_it_does_not_resume_an_organization_attempt(self, client, member, org_draft):
        # Page 1 of the organization's attempt is locked; the personal start
        # page must still ask its own question and start its own attempt.
        finished_page_one = services.complete_page(_answer_page_one(org_draft), 1)
        grant_personal(member.account)
        page = client.get(self.START)
        assert page.context["state"] == "ready" and not page.context["resuming"]

        reply = client.post(self.START, {"took_before": "no"})
        personal = Response.objects.get(membership__isnull=True)
        assert reply.url == url("resume", personal)
        assert personal.pk != org_draft.pk
        assert fresh(finished_page_one).pages_completed == 1  # untouched


def _answer_page_one(response):
    questions = Question.objects.filter(survey_version=response.survey_version, position__lte=5)
    for question in questions:
        response = services.save_answer(response, question.pk, 2)
    return response


# --- erasing an account --------------------------------------------------------


@pytest.mark.django_db
class TestErasure:
    def test_an_account_with_only_an_unfinished_organization_attempt_is_deleted(self, acme, member):
        account = member.account
        grant(member)
        services.start_response(account, member)
        plan = erasure.erase_account(account)
        assert plan.action == erasure.DELETE
        assert not Response.objects.exists() and not Entitlement.objects.exists()
        assert not Account.objects.filter(pk=account.pk).exists()
        assert list(acme[0].memberships.all()) == [acme[1]]

    def test_a_completed_organization_survey_is_kept_and_the_draft_goes(self, acme, member):
        account = member.account
        grant(member)
        done = finish(services.start_response(account, member))
        grant(member)
        services.start_response(account, member)
        spare = grant(member)

        plan = erasure.erase_account(account)

        assert plan.action == erasure.ANONYMISE
        assert list(Response.objects.all()) == [done]
        kept = fresh(done)
        assert kept.status == "submitted" and kept.membership == member
        member.refresh_from_db()
        assert not member.is_active  # shown to the organization as an erased member
        # The draft's licence and the spare one are unused, so both are revoked.
        assert Entitlement.objects.filter(revoked_at__isnull=False).count() == 2
        assert not fresh(spare).is_active and fresh(done.entitlement).is_active

    def test_erasing_locks_the_memberships_before_their_responses(self, member):
        grant(member)
        services.start_response(member.account, member)
        with CaptureQueriesContext(connection) as captured:
            erasure.erase_account(member.account)
        statements = [query["sql"] for query in captured.captured_queries]
        lock = next(
            i
            for i, sql in enumerate(statements)
            if "FOR UPDATE" in sql and Membership._meta.db_table in sql
        )
        delete = next(
            i
            for i, sql in enumerate(statements)
            if sql.startswith("DELETE") and Response._meta.db_table in sql
        )
        assert lock < delete


# --- the staff admin -----------------------------------------------------------


@pytest.mark.django_db
class TestAdmin:
    def test_the_list_and_the_page_say_who_the_attempt_was_taken_for(self, client, member):
        account = member.account
        grant_personal(account)
        personal = services.start_response(account)
        grant(member)
        for_acme = services.start_response(account, member)
        root = Account.objects.create_superuser("root@example.com", PASSWORD)
        client.force_login(root)

        listing = client.get("/admin/responses/response/").content.decode()
        assert "Taken for" in listing and "Personal" in listing and "Acme" in listing

        page = client.get(f"/admin/responses/response/{for_acme.pk}/change/").content.decode()
        assert "Acme" in page and f"Membership {member.pk} in Acme" in page
        page = client.get(f"/admin/responses/response/{personal.pk}/change/").content.decode()
        assert "Personal" in page
