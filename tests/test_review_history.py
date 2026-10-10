"""
Milestone 2, PRs 7 and 8: the review page, submitting, the history and the
result. The person sees a count before submitting and only date, status and tier
afterwards: never a statement and never an answer. A licence revoked after
submitting shows the free tier ("licence withdrawn").
"""

import datetime

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.entitlements import services as licences
from apps.funnel.models import FunnelEvent
from apps.responses import services
from apps.responses.models import Response
from apps.survey.models import Question

from .test_profile import verified_account
from .test_statement_pages import HX, LABELS, fresh, lock, on_page, save, url
from .test_verification import PASSWORD

HISTORY = "/survey/history/"


@pytest.fixture
def bob(client, db):
    account = verified_account("bob@example.com")
    client.force_login(account)
    return account


@pytest.fixture
def draft(bob):
    licences.grant_individual(bob.person, 2, "manual", None)
    return services.save_self_report(services.start_response(bob), False)


@pytest.fixture
def done(draft):
    return services.submit(lock(draft, 5))


def html(client, address):
    return client.get(address).content.decode()


@pytest.mark.django_db
class TestReview:
    def test_shows_the_count_and_a_submit_button_never_the_answers(self, client, draft):
        Question.objects.update(text="Secret statement")
        draft = lock(draft, 5)
        page = html(client, url("review", draft))
        assert "25 of 25 answered" in page and url("submit", draft) in page
        assert "Secret statement" not in page
        for label in LABELS:
            assert label not in page


@pytest.mark.django_db
class TestSubmit:
    def test_submits_and_lands_on_the_result(self, client, draft):
        draft = lock(draft, 5)
        FunnelEvent.objects.all().delete()
        response = client.post(url("submit", draft))
        assert response.url == url("result", draft)
        assert fresh(draft).status == "submitted"
        assert "Submitted." in html(client, url("result", draft))
        assert FunnelEvent.objects.filter(kind="survey_submitted").count() == 1

    def test_a_double_click_submits_once_and_lands_on_the_result(self, client, draft):
        draft = lock(draft, 5)
        client.post(url("submit", draft))
        second = client.post(url("submit", draft), follow=True)
        assert second.redirect_chain[0][0] == url("result", draft)
        assert "You need a licence" not in second.content.decode()
        assert FunnelEvent.objects.filter(kind="survey_submitted").count() == 1

    def test_two_clicks_arriving_together_land_quietly(self, client, draft, monkeypatch):
        draft = lock(draft, 5)

        def already(response):
            raise services.Locked("This survey has been submitted and cannot be changed.")

        monkeypatch.setattr(services, "submit", already)
        response = client.post(url("submit", draft), follow=True)
        assert response.redirect_chain[0][0] == url("result", draft)
        assert "Submitted." not in response.content.decode()

    def test_unfinished_pages_go_back_with_the_reason(self, client, draft):
        draft = lock(draft, 4)
        response = client.post(url("submit", draft), follow=True)
        assert response.redirect_chain[-1][0] == url("page", draft, 5)
        assert "Please finish every page first." in response.content.decode()
        assert fresh(draft).status == "draft"

    def test_a_get_goes_to_the_review(self, client, draft):
        draft = lock(draft, 5)
        assert client.get(url("submit", draft)).url == url("review", draft)
        assert fresh(draft).status == "draft"

    def test_someone_elses_survey_cannot_be_submitted(self, client, bob):
        other = verified_account("carol@example.com")
        licences.grant_individual(other.person, 1, "manual", None)
        licences.grant_individual(bob.person, 1, "manual", None)
        theirs = lock(services.save_self_report(services.start_response(other), False), 5)
        assert client.post(url("submit", theirs)).status_code == 404
        assert fresh(theirs).status == "draft"

    def test_a_click_in_a_forgotten_tab_moves_to_the_result(self, client, done):
        response = save(client, done, on_page(done, 5)[0], 1, **HX)
        assert response["HX-Redirect"] == url("result", done)


@pytest.mark.django_db
class TestWhoGetsIn:
    def test_anonymous_goes_to_login(self, client, done):
        client.logout()
        for address in (HISTORY, url("result", done)):
            assert "/accounts/login/" in client.get(address).url

    def test_unverified_goes_to_the_profile(self, client, db):
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        assert client.get(HISTORY).url == reverse("account_profile")

    def test_someone_elses_result_is_not_found(self, client, bob):
        other = verified_account("carol@example.com")
        licences.grant_individual(other.person, 1, "manual", None)
        theirs = services.submit(
            lock(services.save_self_report(services.start_response(other), False), 5)
        )
        assert client.get(url("result", theirs)).status_code == 404
        assert url("result", theirs) not in html(client, HISTORY)

    def test_an_absurd_id_is_not_found(self, client, bob):
        assert client.get("/survey/99999999999999999999/result/").status_code == 404

    def test_a_draft_has_no_result_yet(self, client, draft):
        assert client.get(url("result", draft)).url == url("resume", draft)

    def test_never_cached(self, client, done):
        for address in (HISTORY, url("result", done)):
            assert "no-store" in client.get(address)["Cache-Control"]

    def test_the_header_and_profile_link_to_history(self, client, bob):
        page = html(client, "/accounts/profile/")
        assert page.count(f'href="{HISTORY}"') == 2 and "My surveys" in page


@pytest.mark.django_db
class TestHistory:
    def test_a_free_account(self, client, bob):
        page = html(client, HISTORY)
        assert "Free account" in page and "You have not taken the survey yet" in page
        assert reverse("responses:start") not in page

    def test_unused_licences_offer_start(self, client, bob):
        licences.grant_individual(bob.person, 1, "manual", None)
        page = html(client, HISTORY)
        assert "You have 1 unused licence<" in page and reverse("responses:start") in page
        licences.grant_individual(bob.person, 1, "manual", None)
        assert "You have 2 unused licences" in html(client, HISTORY)

    def test_an_open_draft_offers_continue(self, client, draft):
        page = html(client, HISTORY)
        assert "Your survey is in progress" in page and url("resume", draft) in page
        assert "In progress · Tier 2" in page

    def test_a_submitted_survey_links_to_its_result(self, client, done):
        page = html(client, HISTORY)
        assert "Submitted · Tier 2" in page and url("result", done) in page
        assert "No unused licence" in page  # the licence is used, not gone

    def test_lists_every_attempt_newest_first(self, client, done):
        licences.grant_individual(done.account.person, 3, "manual", None)
        second = services.save_self_report(services.start_response(done.account), True, "other")
        page = html(client, HISTORY)
        assert page.index(url("resume", second)) < page.index(url("result", done))

    def test_an_upgrade_shows_at_once(self, client, done):
        licences.change_tier(done.entitlement, 3)
        assert "Submitted · Tier 3" in html(client, HISTORY)
        assert "Tier 3" in html(client, url("result", done))


@pytest.mark.django_db
class TestResult:
    def test_shows_the_date_and_tier(self, client, done):
        Response.objects.filter(pk=done.pk).update(
            submitted_at=datetime.datetime(2026, 10, 10, 23, 30, tzinfo=datetime.UTC)
        )
        page = html(client, url("result", done))
        assert "10 October 2026" in page and "Tier 2" in page
        assert "Your results will appear here" in page

    def test_a_licence_revoked_after_submitting_shows_free(self, client, done):
        licences.revoke(done.entitlement)
        assert fresh(done).status == "submitted"  # revoking keeps a submitted survey
        page = html(client, url("result", done))
        assert "Free (licence withdrawn)" in page and "results are not available" in page
        assert "Your results will appear here" not in page
        history = html(client, HISTORY)
        assert "Submitted · Free (licence withdrawn)" in history and "Free account" in history


@pytest.mark.django_db
class TestNeverTheAnswers:
    def test_no_statement_answer_or_self_report_after_submitting(self, client, draft):
        for question in Question.objects.all():
            Question.objects.filter(pk=question.pk).update(text=f"Secret statement {question.pk}")
        draft = services.save_self_report(draft, True, "company")
        done = services.submit(lock(draft, 5))
        for address in (HISTORY, url("result", done)):
            page = html(client, address)
            assert "Secret statement" not in page
            for label in LABELS:
                assert label not in page
            assert "Company" not in page and "taken this survey" not in page

    def test_the_templates_never_receive_the_response(self, client, done):
        for address in (HISTORY, url("result", done)):
            context = client.get(address).context
            assert "response" not in context and "answers" not in context
            for value in context.get("rows") or [context.get("row")]:
                assert "answers" not in value
