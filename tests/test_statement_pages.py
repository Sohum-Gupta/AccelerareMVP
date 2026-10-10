"""
Milestone 2, PR 6: the statement pages, the autosave and the Next button. The
rules live in the services (test_response_services.py); these tests check the
pages wire them up, that only your own draft and only the page you are on can be
reached, and that a background (HTMX) request never gets a page swapped into a
statement's box.
"""

import pytest
from django.urls import reverse

from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.funnel.models import FunnelEvent
from apps.responses import services
from apps.responses.models import Response
from apps.survey.models import Question

from .test_profile import verified_account

HX = {"HTTP_HX_REQUEST": "true"}
LABELS = (
    "This does not describe me",
    "This slightly describes me",
    "This mostly describes me",
    "This describes me very accurately",
)


@pytest.fixture
def bob(client, db):
    account = verified_account("bob@example.com")
    client.force_login(account)
    return account


@pytest.fixture
def draft(bob):
    licences.grant_individual(bob.person, 2, "manual", None)
    return services.save_self_report(services.start_response(bob), False)


def url(name, response, *args):
    return reverse(f"responses:{name}", args=[response.pk, *args])


def on_page(response, page):
    questions = Question.objects.filter(survey_version=response.survey_version)
    return [q for q in questions.order_by("position") if services.page_of(q.position) == page]


def answer(response, page, value=3):
    for question in on_page(response, page):
        response = services.save_answer(response, question.pk, value)
    return response


def lock(response, up_to):
    for page in range(1, up_to + 1):
        response = services.complete_page(answer(response, page), page)
    return response


def save(client, response, question, value, **headers):
    data = {"question": str(question.pk), f"answer-{question.pk}": str(value)}
    return client.post(url("save_answer", response), data, **headers)


def press_next(client, response, page, values):
    """Post the page's form as the browser would: the page number and the ticks shown."""
    data = {"page": str(page)}
    data.update({f"answer-{q.pk}": str(v) for q, v in zip(on_page(response, page), values)})
    return client.post(url("next_page", response), data)


def fresh(response):
    return Response.objects.get(pk=response.pk)


@pytest.mark.django_db
class TestWhoGetsIn:
    def test_anonymous_goes_to_login(self, client, draft):
        client.logout()
        for name, args in (("resume", ()), ("page", (1,)), ("review", ())):
            response = client.get(url(name, draft, *args))
            assert response.status_code == 302 and "/accounts/login/" in response.url

    def test_without_a_licence_every_statement_page_goes_to_the_start(self, client, bob):
        other = verified_account("carol@example.com")
        licences.grant_individual(other.person, 1, "manual", None)
        theirs = services.save_self_report(services.start_response(other), False)
        for name, args in (("resume", ()), ("page", (1,)), ("review", ())):
            response = client.get(url(name, theirs, *args))
            assert response.status_code == 302 and response.url == reverse("responses:start")
        response = client.post(url("next_page", theirs), {"page": "1"})
        assert response.url == reverse("responses:start")

    def test_someone_elses_draft_is_not_found(self, client, draft):
        other = verified_account("carol@example.com")
        licences.grant_individual(other.person, 1, "manual", None)
        theirs = services.save_self_report(services.start_response(other), False)
        question = on_page(theirs, 1)[0]
        assert client.get(url("resume", theirs)).status_code == 404
        assert client.get(url("page", theirs, 1)).status_code == 404
        assert client.get(url("review", theirs)).status_code == 404
        assert save(client, theirs, question, 3).status_code == 404
        assert press_next(client, theirs, 1, [3] * 5).status_code == 404
        assert fresh(theirs).answers == {}

    def test_a_submitted_response_is_not_found(self, client, draft):
        done = services.submit(lock(draft, 5))
        licences.grant_individual(done.account.person, 1, "manual", None)
        assert client.get(url("resume", done)).status_code == 404

    def test_a_draft_on_a_revoked_licence_is_not_found(self, client, draft):
        # revoke() deletes the draft; this is the second lock if one ever survives.
        Entitlement.objects.filter(pk=draft.entitlement_id).update(revoked_at=draft.started_at)
        licences.grant_individual(draft.account.person, 1, "manual", None)
        assert client.get(url("page", draft, 1)).status_code == 404

    def test_an_absurd_id_is_not_found_not_a_crash(self, client, draft):
        assert client.get("/survey/99999999999999999999/").status_code == 404


@pytest.mark.django_db
class TestWhichPage:
    def test_without_the_self_report_it_goes_back_to_the_start(self, client, bob):
        licences.grant_individual(bob.person, 1, "manual", None)
        response = services.start_response(bob)
        assert client.get(url("resume", response)).url == reverse("responses:start")
        assert client.get(url("page", response, 1)).url == reverse("responses:start")

    def test_resume_goes_to_page_1(self, client, draft):
        assert client.get(url("resume", draft)).url == url("page", draft, 1)

    def test_page_1_shows_its_five_statements_and_the_four_labels(self, client, draft):
        html = client.get(url("page", draft, 1)).content.decode()
        for position in range(1, 6):
            assert f"Question {position}<" in html
        assert "Question 6<" not in html
        for label in LABELS:
            assert html.count(label) == 5
        assert "Page 1 of 5" in html and "data-next" in html
        assert url("save_answer", draft) in html and "survey-page.js" in html

    def test_resume_after_answers_out_of_order_lands_on_page_2_with_them_ticked(
        self, client, draft
    ):
        for question in reversed(on_page(draft, 1)):
            draft = services.save_answer(draft, question.pk, 2)
        draft = services.complete_page(draft, 1)
        second, fourth = on_page(draft, 2)[1], on_page(draft, 2)[3]
        draft = services.save_answer(draft, fourth.pk, 4)
        draft = services.save_answer(draft, second.pk, 1)
        assert client.get(url("resume", draft)).url == url("page", draft, 2)
        html = client.get(url("page", draft, 2)).content.decode()
        assert f'name="answer-{second.pk}" value="1" checked' in html
        assert f'name="answer-{fourth.pk}" value="4" checked' in html
        assert html.count(" checked") == 2
        assert "Question 1<" not in html and "Page 2 of 5" in html

    def test_every_other_page_number_goes_to_the_current_page(self, client, draft):
        draft = lock(draft, 1)
        for number in (0, 1, 3, 5, 6, 999, 99999999999999999999):
            response = client.get(f"/survey/{draft.pk}/page/{number}/")
            assert response.status_code == 302 and response.url == url("page", draft, 2)

    def test_the_review_waits_until_every_page_is_locked(self, client, draft):
        assert client.get(url("review", draft)).url == url("page", draft, 1)
        draft = lock(draft, 5)
        assert client.get(url("resume", draft)).url == url("review", draft)
        assert client.get(url("page", draft, 5)).url == url("review", draft)
        html = client.get(url("review", draft)).content.decode()
        assert "All 5 pages are done" in html
        assert "Question" not in html and 'value="3"' not in html

    def test_pages_are_never_cached(self, client, draft):
        response = client.get(url("page", draft, 1))
        assert "no-store" in response["Cache-Control"]

    def test_statement_text_is_escaped(self, client, draft):
        Question.objects.filter(pk=on_page(draft, 1)[0].pk).update(text="<b>Bold</b>")
        html = client.get(url("page", draft, 1)).content.decode()
        assert "&lt;b&gt;Bold&lt;/b&gt;" in html and "<b>Bold</b>" not in html


@pytest.mark.django_db
class TestAutosave:
    def test_a_click_is_saved_and_the_statement_comes_back_saved(self, client, draft):
        question = on_page(draft, 1)[2]
        response = save(client, draft, question, 4, **HX)
        assert response.status_code == 200
        html = response.content.decode()
        assert "Saved" in html and f'name="answer-{question.pk}" value="4" checked' in html
        assert fresh(draft).answers == {str(question.pk): 4}

    def test_changing_a_choice_keeps_the_last_one(self, client, draft):
        question = on_page(draft, 1)[0]
        save(client, draft, question, 1, **HX)
        save(client, draft, question, 3, **HX)
        assert fresh(draft).answers == {str(question.pk): 3}

    def test_a_bad_value_is_a_409_with_the_reason(self, client, draft):
        question = on_page(draft, 1)[0]
        for value in ("0", "5", "abc", "", "3.0", "-1"):
            response = save(client, draft, question, value, **HX)
            assert response.status_code == 409
            assert "Choose a number from 1 to 4" in response.content.decode()
        assert fresh(draft).answers == {}

    def test_a_later_page_is_refused_without_showing_its_statement(self, client, draft):
        later = on_page(draft, 3)[0]
        Question.objects.filter(pk=later.pk).update(text="Secret later statement")
        response = save(client, draft, later, 3, **HX)
        assert response.status_code == 409
        assert "Secret later statement" not in response.content.decode()
        assert fresh(draft).answers == {}

    def test_unknown_or_malformed_questions_are_refused(self, client, draft):
        for question_id in ("999999", "abc", "", "99999999999999999999"):
            data = {"question": question_id, f"answer-{question_id}": "3"}
            response = client.post(url("save_answer", draft), data, **HX)
            assert response.status_code == 409
        assert fresh(draft).answers == {}

    def test_a_page_locked_in_another_tab_reloads_the_window(self, client, draft):
        draft = lock(draft, 1)
        response = save(client, draft, on_page(draft, 1)[0], 1, **HX)
        assert response.status_code == 200 and response["HX-Redirect"] == url("resume", draft)
        assert response.content == b""
        assert fresh(draft).answers[str(on_page(draft, 1)[0].pk)] == 3

    def test_an_expired_login_reloads_the_window_on_the_login_page(self, client, draft):
        client.logout()
        response = save(client, draft, on_page(draft, 1)[0], 2, **HX)
        assert response.status_code == 200 and "/accounts/login/" in response["HX-Redirect"]
        assert fresh(draft).answers == {}

    def test_a_lost_licence_reloads_the_window_on_the_start_page(self, client, draft):
        licences.revoke(draft.entitlement)
        response = client.post(url("save_answer", draft), {"question": "1"}, **HX)
        assert response["HX-Redirect"] == reverse("responses:start")

    def test_a_draft_deleted_mid_save_goes_to_the_start(self, client, draft, monkeypatch):
        def gone(*args):
            raise Response.DoesNotExist

        monkeypatch.setattr(services, "save_answer", gone)
        response = save(client, draft, on_page(draft, 1)[0], 2, **HX)
        assert response["HX-Redirect"] == reverse("responses:start")

    def test_a_get_goes_to_the_page_not_an_error(self, client, draft):
        # After logging in again, the login page sends you back here with a GET.
        assert client.get(url("save_answer", draft)).url == url("resume", draft)
        assert client.get(url("next_page", draft)).url == url("resume", draft)

    def test_never_cached(self, client, draft):
        response = save(client, draft, on_page(draft, 1)[0], 2, **HX)
        assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
class TestNext:
    def test_saves_the_ticks_shown_and_locks_the_page_without_autosave(self, client, draft):
        response = press_next(client, draft, 1, [1, 2, 3, 4, 1])
        assert response.url == url("resume", draft)
        draft = fresh(draft)
        assert draft.pages_completed == 1
        assert [draft.answers[str(q.pk)] for q in on_page(draft, 1)] == [1, 2, 3, 4, 1]

    def test_what_the_page_shows_wins_over_another_tabs_save(self, client, draft):
        draft = answer(draft, 1, value=1)
        press_next(client, draft, 1, [4] * 5)
        assert set(fresh(draft).answers.values()) == {4}

    def test_four_of_five_stays_on_the_page_with_the_reason(self, client, draft):
        response = press_next(client, draft, 1, [3] * 4)
        assert response.url == url("resume", draft)
        html = client.get(url("page", draft, 1)).content.decode()
        assert "Please answer all 5 statements on this page first." in html
        draft = fresh(draft)
        assert draft.pages_completed == 0 and len(draft.answers) == 4

    def test_a_double_click_locks_one_page_and_says_nothing(self, client, draft):
        press_next(client, draft, 1, [3] * 5)
        answer(fresh(draft), 2)
        second = press_next(client, draft, 1, [3] * 5)
        assert second.url == url("resume", draft)
        assert fresh(draft).pages_completed == 1
        html = client.get(url("page", draft, 2)).content.decode()
        assert "locked" not in html.split("<main")[1].split("Next</strong>")[0]

    def test_a_tampered_page_number_locks_nothing(self, client, draft):
        draft = answer(draft, 1)
        for page in ("3", "0", "abc", ""):
            client.post(url("next_page", draft), {"page": page})
        assert fresh(draft).pages_completed == 0

    def test_a_tampered_value_saves_nothing(self, client, draft):
        press_next(client, draft, 1, [3, 3, 3, 3, 9])
        draft = fresh(draft)
        assert draft.pages_completed == 0 and draft.answers == {}

    def test_ticks_for_a_later_page_are_refused(self, client, draft):
        data = {"page": "1"}
        data.update({f"answer-{q.pk}": "3" for q in on_page(draft, 1) + on_page(draft, 2)})
        client.post(url("next_page", draft), data)
        draft = fresh(draft)
        assert draft.pages_completed == 0 and draft.answers == {}

    def test_five_pages_through_the_buttons_reach_the_review(self, client, draft):
        FunnelEvent.objects.all().delete()
        for page in range(1, 6):
            assert client.get(url("resume", draft)).url == url("page", draft, page)
            press_next(client, draft, page, [2] * 5)
        assert client.get(url("resume", draft)).url == url("review", draft)
        assert FunnelEvent.objects.filter(kind="page_locked").count() == 5
        assert fresh(draft).status == "draft"  # submitting is PR 7
