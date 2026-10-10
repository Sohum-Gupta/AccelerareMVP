"""
Milestone 2, PR 5: the start page (disclosure and self-report), the licence gate
on the pages after it, and the link from the profile. The rules live in the
services (test_response_services.py); these tests check the page wires them up
and that opening the page never costs a licence.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.models import Account
from apps.entitlements import services as licences
from apps.entitlements.decorators import survey_access_required
from apps.funnel.models import FunnelEvent
from apps.responses import services
from apps.responses.models import Response
from apps.survey.models import Question

from .test_profile import verified_account
from .test_verification import PASSWORD

START = "/survey/start/"
NOTICE = "You need a licence to take the survey"


@pytest.fixture
def bob(client, db):
    account = verified_account("bob@example.com")
    client.force_login(account)
    return account


@pytest.fixture
def licensed(bob):
    licences.grant_individual(bob.person, 2, "manual", None)
    return bob


def page(client):
    return client.get(START).content.decode()


def first_page_answered(response):
    questions = Question.objects.filter(survey_version=response.survey_version).order_by("position")
    for question in questions[:5]:
        response = services.save_answer(response, question.pk, 2)
    return response


@pytest.mark.django_db
class TestWhoGetsIn:
    def test_anonymous_goes_to_login(self, client):
        response = client.get(START)
        assert response.status_code == 302 and "/accounts/login/" in response.url

    def test_unverified_goes_to_the_profile(self, client, db):
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        response = client.get(START)
        assert response.status_code == 302 and response.url == reverse("account_profile")

    def test_the_profile_links_to_the_survey_history(self, client, bob):
        assert "/survey/history/" in client.get("/accounts/profile/").content.decode()


@pytest.mark.django_db
class TestWithoutALicence:
    def test_sees_the_disclosure_and_the_notice_but_no_form(self, client, bob):
        html = page(client)
        assert "Who sees your answers" in html and "Accelerare" in html
        assert NOTICE in html
        assert 'name="took_before"' not in html

    def test_a_direct_post_changes_nothing(self, client, bob):
        response = client.post(START, {"took_before": "no"})
        assert response.status_code == 200 and NOTICE in response.content.decode()
        assert not Response.objects.exists()
        assert not FunnelEvent.objects.filter(kind="survey_started").exists()

    def test_a_revoked_licence_mid_attempt_shows_the_notice(self, client, licensed):
        client.post(START, {"took_before": "no"})
        licences.revoke(Response.objects.get().entitlement)
        assert NOTICE in page(client)


@pytest.mark.django_db
class TestWithALicence:
    def test_opening_the_page_costs_nothing(self, client, licensed):
        html = page(client)
        assert 'name="took_before"' in html and NOTICE not in html
        assert "Start the survey" in html
        assert not Response.objects.exists()
        assert licences.unused_licence(licensed) is not None

    def test_yes_and_how_starts_the_survey(self, client, licensed):
        response = client.post(START, {"took_before": "yes", "took_before_via": "company"})
        draft = Response.objects.get()
        assert response.status_code == 302 and response.url == f"/survey/{draft.pk}/"
        assert draft.account == licensed and draft.status == "draft"
        assert draft.took_before is True and draft.took_before_via == "company"
        assert licences.unused_licence(licensed) is None  # the licence is consumed
        assert FunnelEvent.objects.filter(kind="survey_started").count() == 1

    def test_no_stores_an_empty_how(self, client, licensed):
        client.post(START, {"took_before": "no", "took_before_via": "other"})
        draft = Response.objects.get()
        assert draft.took_before is False and draft.took_before_via == ""

    def test_yes_without_how_is_a_field_error_and_costs_nothing(self, client, licensed):
        response = client.post(START, {"took_before": "yes", "took_before_via": ""})
        assert response.status_code == 200
        assert "Please say how you took it." in response.content.decode()
        assert not Response.objects.exists()

    def test_missing_or_tampered_values_are_refused(self, client, licensed):
        for data in (
            {},
            {"took_before": "maybe"},
            {"took_before": "yes", "took_before_via": "school"},
        ):
            assert client.post(START, data).status_code == 200
        assert not Response.objects.exists()

    def test_posting_again_resumes_the_same_draft_and_updates_the_answer(self, client, licensed):
        client.post(START, {"took_before": "yes", "took_before_via": "individual"})
        licences.grant_individual(licensed.person, 1, "manual", None)  # must not be consumed
        client.post(START, {"took_before": "no"})
        draft = Response.objects.get()
        assert draft.took_before is False and draft.took_before_via == ""
        assert licences.unused_licence(licensed) is not None
        assert FunnelEvent.objects.filter(kind="survey_started").count() == 1

    def test_the_form_is_prefilled_when_resuming(self, client, licensed):
        client.post(START, {"took_before": "yes", "took_before_via": "other"})
        html = page(client)
        assert "You have already started" in html and "Save and continue" in html
        assert 'value="yes" id="id_took_before_0" required checked' in html
        assert '<option value="other" selected>' in html

    def test_once_page_1_is_locked_the_question_is_gone(self, client, licensed):
        client.post(START, {"took_before": "no"})
        draft = first_page_answered(Response.objects.get())
        services.complete_page(draft, 1)
        html = page(client)
        assert "Your survey is in progress" in html and 'name="took_before"' not in html
        assert f'href="/survey/{draft.pk}/"' in html and "Continue" in html
        response = client.post(START, {"took_before": "yes", "took_before_via": "other"})
        assert response.status_code == 302
        draft.refresh_from_db()
        assert draft.took_before is False

    def test_a_service_refusal_is_shown_not_a_crash(self, client, licensed, monkeypatch):
        def refuse(account):
            raise services.NoLicence("You need a licence to take the survey.")

        monkeypatch.setattr(services, "start_response", refuse)
        response = client.post(START, {"took_before": "no"})
        assert response.status_code == 200 and NOTICE in response.content.decode()

    def test_the_page_shows_no_statement(self, client, licensed):
        assert "Question 1" not in page(client)
        client.post(START, {"took_before": "no"})
        assert "Question 1" not in page(client)


# --- the gate on the pages after this one ------------------------------------------


@survey_access_required
def guarded(request):
    return HttpResponse("statements")


def call_guarded(client, account):
    request = RequestFactory().get("/survey/page/")
    request.user = account
    request.session = client.session
    request._messages = FallbackStorage(request)
    return guarded(request)


@pytest.mark.django_db
class TestSurveyAccessRequired:
    def test_anonymous_goes_to_login(self, client):
        response = call_guarded(client, AnonymousUser())
        assert response.status_code == 302 and "/accounts/login/" in response.url

    def test_unverified_goes_to_the_profile(self, client, db):
        account = Account.objects.create_superuser("root@example.com", PASSWORD)
        response = call_guarded(client, account)
        assert response.status_code == 302 and response.url == reverse("account_profile")

    def test_no_licence_goes_to_the_start_page(self, client, bob):
        response = call_guarded(client, bob)
        assert response.status_code == 302 and response.url == START

    def test_an_unused_licence_or_an_open_draft_gets_through(self, client, licensed):
        assert call_guarded(client, licensed).content == b"statements"
        services.start_response(licensed)
        assert call_guarded(client, licensed).content == b"statements"

    def test_after_submitting_the_gate_closes_again(self, client, licensed):
        draft = services.save_self_report(services.start_response(licensed), False)
        for page_number in range(1, 6):
            questions = Question.objects.filter(survey_version=draft.survey_version).order_by(
                "position"
            )[(page_number - 1) * 5 : page_number * 5]
            for question in questions:
                draft = services.save_answer(draft, question.pk, 3)
            draft = services.complete_page(draft, page_number)
        services.submit(draft)
        assert call_guarded(client, licensed).status_code == 302
