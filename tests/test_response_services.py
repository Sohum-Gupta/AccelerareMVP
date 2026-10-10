"""
Milestone 2, PR 4: the response services. Starting consumes exactly one licence,
answers are checked, Next needs all five, submit needs all 25, a submitted
response never changes, every write takes a row lock, and the funnel records
what happened and nothing that was refused.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account, Person
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.funnel.models import FunnelEvent
from apps.responses import services
from apps.responses.models import Response
from apps.survey.models import Question, SurveyVersion
from apps.survey.services import PAGE_SIZE, current_version

from .test_profile import verified_account

Kind = FunnelEvent.Kind


@pytest.fixture
def bob(db):
    return verified_account("bob@example.com")


@pytest.fixture
def licensed(bob):
    licences.grant_individual(bob.person, 2, "manual", None)
    return bob


@pytest.fixture
def draft(licensed):
    response = services.start_response(licensed)
    return services.save_self_report(response, False)


def grant(account, tier=1, source="manual"):
    return licences.grant_individual(account.person, tier, source, None)


def questions(response=None):
    version = response.survey_version if response else current_version()
    return list(Question.objects.filter(survey_version=version).order_by("position"))


def on_page(page, response=None):
    return [q for q in questions(response) if services.page_of(q.position) == page]


def answer_page(response, page, value=3, leave_out=0):
    """Answer the statements on a page; leave_out skips that many from the end."""
    for question in on_page(page, response)[: PAGE_SIZE - leave_out]:
        response = services.save_answer(response, question.pk, value)
    return response


def finish_pages(response, up_to):
    for page in range(1, up_to + 1):
        response = answer_page(response, page)
        response = services.complete_page(response, page)
    return response


def events(kind=None):
    rows = FunnelEvent.objects.order_by("id")
    if kind:
        rows = rows.filter(kind=kind)
    return list(rows)


def locked_tables(queries):
    """Which tables were read with FOR UPDATE in the captured SQL."""
    return {
        word.strip('"')
        for query in queries
        if "FOR UPDATE" in query["sql"]
        for word in query["sql"].split()
        if word.startswith('"') and "_" in word and "." not in word
    }


@pytest.mark.django_db
class TestStart:
    def test_no_licence_is_refused(self, bob):
        with pytest.raises(services.NoLicence):
            services.start_response(bob)
        assert not Response.objects.exists()

    def test_one_licence_creates_a_draft_on_it(self, bob):
        licence = grant(bob, 3)
        response = services.start_response(bob)
        assert response.status == "draft" and response.entitlement == licence
        assert response.survey_version == current_version() and response.account == bob
        assert response.answers == {} and response.pages_completed == 0

    def test_called_twice_returns_the_same_draft_and_counts_one_start(self, licensed):
        first = services.start_response(licensed)
        grant(licensed)  # a spare licence must not be consumed
        assert services.start_response(licensed) == first
        assert Response.objects.count() == 1
        assert len(events(Kind.SURVEY_STARTED)) == 1
        assert licences.unused_licence(licensed) is not None

    def test_after_submit_a_new_start_needs_another_licence(self, draft):
        services.submit(finish_pages(draft, 5))
        with pytest.raises(services.NoLicence):
            services.start_response(draft.account)
        second = grant(draft.account)
        again = services.start_response(draft.account)
        assert again.pk != draft.pk and again.entitlement == second

    def test_the_oldest_unused_licence_is_consumed_first(self, bob):
        older = grant(bob, 1)
        grant(bob, 3)
        assert services.start_response(bob).entitlement == older

    def test_locks_the_account_the_person_and_the_licences(self, licensed):
        with CaptureQueriesContext(connection) as captured:
            services.start_response(licensed)
        locked = locked_tables(captured.captured_queries)
        assert Account._meta.db_table in locked
        assert Person._meta.db_table in locked
        assert Entitlement._meta.db_table in locked

    def test_the_funnel_records_the_tier_and_source(self, bob):
        grant(bob, 3, "purchase")
        FunnelEvent.objects.all().delete()
        services.start_response(bob)
        (event,) = events()
        assert (event.kind, event.tier, event.source) == (Kind.SURVEY_STARTED, 3, "purchase")

    def test_an_erased_or_inactive_account_is_refused(self, licensed):
        Account.objects.filter(pk=licensed.pk).update(is_active=False)
        licensed.refresh_from_db()
        with pytest.raises(services.Refused):
            services.start_response(licensed)
        assert not Response.objects.exists()

    def test_a_person_with_no_survey_published_is_refused(self, licensed, monkeypatch):
        monkeypatch.setattr(services, "current_version", lambda: None)
        with pytest.raises(services.Refused, match="No survey"):
            services.start_response(licensed)
        assert licences.unused_licence(licensed) is not None  # nothing consumed


@pytest.mark.django_db
class TestRevokeAndStart:
    def test_revoking_deletes_the_unfinished_attempt_so_a_new_licence_works(self, draft):
        answer_page(draft, 1)
        _, deleted = licences.revoke(draft.entitlement)
        assert deleted and not Response.objects.filter(pk=draft.pk).exists()
        with pytest.raises(services.NoLicence):
            services.start_response(draft.account)
        fresh = grant(draft.account)
        assert services.start_response(draft.account).entitlement == fresh

    def test_revoking_keeps_a_submitted_response(self, draft):
        done = services.submit(finish_pages(draft, 5))
        _, deleted = licences.revoke(done.entitlement)
        assert not deleted
        done.refresh_from_db()
        assert done.status == "submitted" and done.entitlement.revoked_at is not None

    def test_revoking_an_unused_licence_deletes_nothing(self, bob):
        _, deleted = licences.revoke(grant(bob))
        assert not deleted

    def test_the_admin_action_says_what_it_deleted(self, client, draft):
        from django.contrib.admin.models import LogEntry

        from .test_verification import PASSWORD

        root = Account.objects.create_superuser("root@example.com", PASSWORD)
        client.force_login(root)
        spare = grant(draft.account)
        response = client.post(
            "/admin/entitlements/entitlement/",
            {"action": "revoke_selected", "_selected_action": [draft.entitlement.pk, spare.pk]},
            follow=True,
        )
        page = response.content.decode()
        assert "Revoked 2 licence(s). Deleted 1 unfinished attempt(s)" in page
        messages = set(LogEntry.objects.values_list("change_message", flat=True))
        assert messages == {"Revoked", "Revoked; the unfinished attempt on it was deleted"}
        assert not Response.objects.exists()


@pytest.mark.django_db
class TestSelfReport:
    def test_yes_with_how(self, licensed):
        response = services.start_response(licensed)
        response = services.save_self_report(response, True, "company")
        assert response.took_before is True and response.took_before_via == "company"
        response.refresh_from_db()
        assert response.took_before_via == "company"

    def test_no_stores_an_empty_how_whatever_was_sent(self, licensed):
        response = services.start_response(licensed)
        response = services.save_self_report(response, True, "other")
        response = services.save_self_report(response, False, "company")
        assert response.took_before is False and response.took_before_via == ""

    def test_yes_needs_a_valid_how(self, licensed):
        response = services.start_response(licensed)
        for via in ("", "school", None, 1, "Company"):
            with pytest.raises(services.Invalid):
                services.save_self_report(response, True, via)
        response.refresh_from_db()
        assert response.took_before is None

    def test_yes_or_no_must_be_a_real_bool(self, licensed):
        response = services.start_response(licensed)
        for value in (None, 1, 0, "yes", "True"):
            with pytest.raises(services.Invalid):
                services.save_self_report(response, value, "other")

    def test_cannot_change_once_page_1_is_locked(self, draft):
        draft = services.complete_page(answer_page(draft, 1), 1)
        with pytest.raises(services.Locked):
            services.save_self_report(draft, True, "other")
        draft.refresh_from_db()
        assert draft.took_before is False

    def test_cannot_change_after_submit(self, draft):
        done = services.submit(finish_pages(draft, 5))
        with pytest.raises(services.Locked):
            services.save_self_report(done, True, "other")

    def test_takes_the_lock(self, licensed):
        response = services.start_response(licensed)
        with CaptureQueriesContext(connection) as captured:
            services.save_self_report(response, False)
        assert Response._meta.db_table in locked_tables(captured.captured_queries)


@pytest.mark.django_db
class TestSaveAnswer:
    def test_stores_the_answer_under_the_question_id(self, draft):
        question = on_page(1)[0]
        response = services.save_answer(draft, question.pk, 4)
        assert response.answers == {str(question.pk): 4}
        response.refresh_from_db()
        assert response.answers == {str(question.pk): 4}

    def test_accepts_the_id_as_a_string_as_a_form_sends_it(self, draft):
        question = on_page(1)[0]
        response = services.save_answer(draft, str(question.pk), 1)
        assert response.answers == {str(question.pk): 1}

    def test_an_answer_can_change_while_the_page_is_open(self, draft):
        question = on_page(1)[0]
        services.save_answer(draft, question.pk, 1)
        response = services.save_answer(draft, question.pk, 4)
        assert response.answers == {str(question.pk): 4}

    def test_rejects_values_outside_the_range_and_wrong_types(self, draft):
        question = on_page(1)[0]
        for value in (0, 5, -1, "3", 3.0, True, False, None):
            with pytest.raises(services.Invalid):
                services.save_answer(draft, question.pk, value)
        draft.refresh_from_db()
        assert draft.answers == {}

    def test_rejects_unknown_and_malformed_question_ids(self, draft):
        for question_id in (999999, 0, -1, "abc", "", None, True, 1.5, "１"):
            with pytest.raises(services.Invalid):
                services.save_answer(draft, question_id, 3)

    def test_rejects_a_question_from_another_survey_version(self, draft):
        other = SurveyVersion.objects.create(
            number=99, published_at=timezone.now(), question_count=1
        )
        foreign = Question.objects.create(survey_version=other, position=1, text="Question 1")
        with pytest.raises(services.Invalid):
            services.save_answer(draft, foreign.pk, 3)

    def test_only_the_page_being_answered_takes_answers(self, draft):
        with pytest.raises(services.Invalid, match="earlier pages"):
            services.save_answer(draft, on_page(2)[0].pk, 2)
        draft = services.complete_page(answer_page(draft, 1), 1)
        with pytest.raises(services.Locked):
            services.save_answer(draft, on_page(1)[0].pk, 2)
        with pytest.raises(services.Invalid, match="earlier pages"):
            services.save_answer(draft, on_page(3)[0].pk, 2)
        response = services.save_answer(draft, on_page(2)[0].pk, 2)
        assert str(on_page(2)[0].pk) in response.answers
        assert str(on_page(3)[0].pk) not in response.answers

    def test_rejects_a_submitted_response(self, draft):
        done = services.submit(finish_pages(draft, 5))
        with pytest.raises(services.Locked):
            services.save_answer(done, on_page(5)[0].pk, 1)

    def test_a_deleted_draft_raises_does_not_exist_not_a_refusal(self, draft):
        pk = draft.pk
        Response.objects.filter(pk=pk).delete()
        with pytest.raises(Response.DoesNotExist):
            services.save_answer(draft, on_page(1)[0].pk, 1)

    def test_takes_the_lock(self, draft):
        with CaptureQueriesContext(connection) as captured:
            services.save_answer(draft, on_page(1)[0].pk, 3)
        assert Response._meta.db_table in locked_tables(captured.captured_queries)


@pytest.mark.django_db
class TestCompletePage:
    def test_four_of_five_is_refused_and_five_succeeds(self, draft):
        draft = answer_page(draft, 1, leave_out=1)
        with pytest.raises(services.Incomplete):
            services.complete_page(draft, 1)
        draft = answer_page(draft, 1)
        response = services.complete_page(draft, 1)
        assert response.pages_completed == 1
        response.refresh_from_db()
        assert response.pages_completed == 1

    def test_refuses_a_page_that_is_not_next(self, draft):
        draft = answer_page(draft, 1)
        with pytest.raises(services.Invalid):
            services.complete_page(draft, 2)
        draft = services.complete_page(draft, 1)
        with pytest.raises(services.Locked):  # a double click on Next
            services.complete_page(draft, 1)
        assert services.complete_page(answer_page(draft, 2), 2).pages_completed == 2

    def test_refuses_pages_that_do_not_exist(self, draft):
        for page in (0, 6, -1, None, "x", True, 2.0):
            with pytest.raises(services.Invalid):
                services.complete_page(draft, page)

    def test_accepts_the_page_as_a_string(self, draft):
        assert services.complete_page(answer_page(draft, 1), "1").pages_completed == 1

    def test_page_1_needs_the_self_report(self, licensed):
        response = answer_page(services.start_response(licensed), 1)
        with pytest.raises(services.Incomplete, match="taken this survey before"):
            services.complete_page(response, 1)
        response = services.save_self_report(response, True, "individual")
        assert services.complete_page(response, 1).pages_completed == 1

    def test_answers_saved_out_of_order_still_count(self, draft):
        for question in reversed(on_page(1)):
            draft = services.save_answer(draft, question.pk, 2)
        assert services.complete_page(draft, 1).pages_completed == 1

    def test_saves_the_answers_shown_on_the_page_then_locks(self, draft):
        first, *rest = on_page(1)
        draft = services.save_answer(draft, first.pk, 1)  # another tab, say
        shown = {str(q.pk): 4 for q in on_page(1)}
        response = services.complete_page(draft, 1, shown)
        assert response.pages_completed == 1 and response.answers == shown
        response.refresh_from_db()
        assert response.answers == shown

    def test_shown_answers_fill_in_a_failed_autosave(self, draft):
        *saved, missed = on_page(1)
        for question in saved:
            draft = services.save_answer(draft, question.pk, 3)
        response = services.complete_page(draft, 1, {str(missed.pk): 2})
        assert response.answers[str(missed.pk)] == 2

    def test_a_bad_shown_answer_changes_nothing(self, draft):
        draft = answer_page(draft, 1, value=3)
        bad_value = {str(on_page(1)[0].pk): 9}
        later_page = {str(on_page(2)[0].pk): 3}
        unknown = {"999999": 3}
        for shown, refusal in (
            (bad_value, services.Invalid),
            (later_page, services.Invalid),
            (unknown, services.Invalid),
        ):
            with pytest.raises(refusal):
                services.complete_page(draft, 1, {str(on_page(1)[1].pk): 1, **shown})
        draft.refresh_from_db()
        assert draft.pages_completed == 0
        assert set(draft.answers.values()) == {3}

    def test_shown_answers_do_not_unlock_a_locked_page(self, draft):
        draft = services.complete_page(answer_page(draft, 1, value=3), 1)
        with pytest.raises(services.Locked):
            services.complete_page(draft, 1, {str(on_page(1)[0].pk): 1})
        draft.refresh_from_db()
        assert draft.answers[str(on_page(1)[0].pk)] == 3

    def test_refuses_after_submit(self, draft):
        done = services.submit(finish_pages(draft, 5))
        with pytest.raises(services.Locked):
            services.complete_page(done, 5)

    def test_records_the_page_in_the_funnel(self, draft):
        FunnelEvent.objects.all().delete()
        services.complete_page(answer_page(draft, 1), 1)
        (event,) = events()
        assert (event.kind, event.page, event.tier, event.source) == (
            Kind.PAGE_LOCKED,
            1,
            2,
            "manual",
        )

    def test_takes_the_lock(self, draft):
        draft = answer_page(draft, 1)
        with CaptureQueriesContext(connection) as captured:
            services.complete_page(draft, 1)
        assert Response._meta.db_table in locked_tables(captured.captured_queries)


@pytest.mark.django_db
class TestSubmit:
    def test_four_pages_locked_is_refused(self, draft):
        draft = answer_page(finish_pages(draft, 4), 5)
        with pytest.raises(services.Incomplete):
            services.submit(draft)
        draft.refresh_from_db()
        assert draft.status == "draft" and draft.submitted_at is None

    def test_a_missing_answer_is_refused_even_with_every_page_locked(self, draft):
        draft = finish_pages(draft, 5)
        answers = dict(draft.answers)
        answers.pop(str(on_page(3)[2].pk))
        Response.objects.filter(pk=draft.pk).update(answers=answers)
        with pytest.raises(services.Incomplete, match="1 statement"):
            services.submit(draft)

    def test_five_pages_and_25_answers_submit(self, draft):
        before = timezone.now()
        done = services.submit(finish_pages(draft, 5))
        assert done.status == "submitted" and done.submitted_at >= before
        done.refresh_from_db()
        assert done.status == "submitted" and len(done.answers) == 25

    def test_after_submit_nothing_can_change(self, draft):
        done = services.submit(finish_pages(draft, 5))
        with pytest.raises(services.Locked):
            services.save_answer(done, on_page(1)[0].pk, 1)
        with pytest.raises(services.Locked):
            services.submit(done)
        done.refresh_from_db()
        assert done.status == "submitted"

    def test_records_the_tier_and_source(self, bob):
        grant(bob, 3, "purchase")
        draft = services.save_self_report(services.start_response(bob), False)
        FunnelEvent.objects.all().delete()
        services.submit(finish_pages(draft, 5))
        event = events(Kind.SURVEY_SUBMITTED)[0]
        assert (event.tier, event.source) == (3, "purchase")

    def test_takes_the_lock(self, draft):
        draft = finish_pages(draft, 5)
        with CaptureQueriesContext(connection) as captured:
            services.submit(draft)
        assert Response._meta.db_table in locked_tables(captured.captured_queries)


@pytest.mark.django_db
class TestFunnel:
    def test_a_full_run_records_the_right_sequence(self, licensed):
        FunnelEvent.objects.all().delete()
        response = services.save_self_report(services.start_response(licensed), False)
        services.submit(finish_pages(response, 5))
        kinds = [e.kind for e in events()]
        assert kinds == [Kind.SURVEY_STARTED] + [Kind.PAGE_LOCKED] * 5 + [Kind.SURVEY_SUBMITTED]
        assert [e.page for e in events(Kind.PAGE_LOCKED)] == [1, 2, 3, 4, 5]

    def test_refused_calls_record_nothing(self, draft):
        unlicensed = verified_account("carol@example.com")
        count = FunnelEvent.objects.count()
        for call in (
            lambda: services.start_response(unlicensed),
            lambda: services.save_answer(draft, on_page(1)[0].pk, 9),
            lambda: services.complete_page(draft, 1),
            lambda: services.complete_page(draft, 2),
            lambda: services.submit(draft),
            lambda: services.save_self_report(draft, "maybe"),
        ):
            with pytest.raises(services.Refused):
                call()
        assert FunnelEvent.objects.count() == count

    def test_the_refusals_share_a_base_class(self):
        for cls in (services.NoLicence, services.Locked, services.Incomplete, services.Invalid):
            assert issubclass(cls, services.Refused)


@pytest.mark.django_db
class TestErasure:
    def test_erasing_during_an_attempt_deletes_the_draft_and_blocks_a_restart(self, draft):
        answer_page(draft, 1)
        erasure.erase_account(draft.account)
        assert not Response.objects.exists()
        account = Account.objects.filter(pk=draft.account_id).first()
        if account is not None:  # stripped rather than deleted
            with pytest.raises(services.Refused):
                services.start_response(account)
