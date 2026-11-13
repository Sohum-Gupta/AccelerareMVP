"""
Milestone 3, PR 7: the survey pages per context.

/survey/start/ is the personal start page and /survey/start/<slug>/ the one for
an organization, which only an active member can open. The organization's page
says what its admins will see before anything is started. "My surveys" offers
Start or Continue for each context and labels every attempt with its context;
the result page says who the survey was taken for.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.enterprises import services as orgs
from apps.enterprises.models import Enterprise, Membership
from apps.funnel.models import FunnelEvent
from apps.responses import services
from apps.responses import views as response_views
from apps.responses.models import Response
from apps.survey.models import Question

from .orgs import new_member, org_with_admin
from .test_profile import verified_account
from .test_response_context import acme, finish, fresh, grant, grant_personal, member  # noqa: F401
from .test_verification import PASSWORD

START = "/survey/start/"
ACME = "/survey/start/acme/"
HISTORY = "/survey/history/"
NOTICE = "You need a licence to take the survey for Acme"


@pytest.fixture
def bob(client, member):
    """Bob, a member of Acme, logged in."""
    client.force_login(member.account)
    return member.account


def html(client, address):
    return client.get(address).content.decode()


def url(name, response, *args):
    return reverse(f"responses:{name}", args=[response.pk, *args])


def answer_page_one(response):
    questions = Question.objects.filter(survey_version=response.survey_version, position__lte=5)
    for question in questions:
        response = services.save_answer(response, question.pk, 2)
    return response


# --- who can open an organization's start page ---------------------------------


@pytest.mark.django_db
class TestWhoGetsIn:
    def test_anonymous_goes_to_login(self, client, member):
        response = client.get(ACME)
        assert response.status_code == 302 and "/accounts/login/" in response.url

    def test_unverified_goes_to_the_profile(self, client, member):
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        assert client.get(ACME).url == reverse("account_profile")

    def test_someone_who_is_not_a_member_gets_not_found(self, client, member):
        grant(member)
        outsider = verified_account("carol@example.com")
        grant_personal(outsider)
        client.force_login(outsider)
        assert client.get(ACME).status_code == 404
        assert client.post(ACME, {"took_before": "no"}).status_code == 404
        assert not Response.objects.exists()

    def test_an_organization_that_does_not_exist_looks_exactly_the_same(self, client, bob):
        missing = client.get("/survey/start/no-such-place/")
        org_with_admin("Other")
        not_mine = client.get("/survey/start/other/")
        assert missing.status_code == not_mine.status_code == 404
        assert missing.content == not_mine.content

    def test_a_deactivated_member_gets_not_found(self, client, acme, member, bob):
        grant(member)
        orgs.deactivate_membership(member, by=acme[1])
        assert client.get(ACME).status_code == 404
        assert client.post(ACME, {"took_before": "no"}).status_code == 404
        assert not Response.objects.exists()

    def test_a_member_of_another_organization_cannot_use_this_one(self, client, member):
        _, other_admin = org_with_admin("Other")
        grant(other_admin)
        client.force_login(other_admin.account)
        assert client.get("/survey/start/other/").status_code == 200
        assert client.get(ACME).status_code == 404

    def test_an_admin_is_a_member_too(self, client, acme):
        grant(acme[1])
        client.force_login(acme[1].account)
        assert 'name="took_before"' in html(client, ACME)


# --- the organization's start page ---------------------------------------------


@pytest.mark.django_db
class TestWithoutALicence:
    def test_sees_the_disclosure_and_the_notice_but_no_form(self, client, bob):
        page = html(client, ACME)
        assert "You are taking this survey for <strong>Acme</strong>" in page
        assert NOTICE in page and 'name="took_before"' not in page

    def test_a_personal_licence_is_no_help(self, client, bob):
        grant_personal(bob)
        assert NOTICE in html(client, ACME)
        response = client.post(ACME, {"took_before": "no"})
        assert response.status_code == 200 and NOTICE in response.content.decode()
        assert not Response.objects.exists()

    def test_a_licence_for_another_organization_is_no_help(self, client, bob):
        other, _ = org_with_admin("Other")
        elsewhere = Membership.objects.create(enterprise=other, account=bob)
        grant(elsewhere)
        assert NOTICE in html(client, ACME)
        assert 'name="took_before"' in html(client, "/survey/start/other/")


@pytest.mark.django_db
class TestWithALicence:
    @pytest.fixture(autouse=True)
    def licensed(self, member):
        return grant(member, 2)

    def test_the_page_says_what_the_organization_will_see(self, client, bob):
        page = html(client, ACME)
        assert "<strong>Acme never sees your answers.</strong>" in page
        assert "The admins of Acme can see:" in page and "They cannot see:" in page
        for told in (
            "whether it is in progress or submitted",
            "the dates you started and submitted it",
            "its results level",
            "your results for this survey, once results are available",
            "how far through the survey you are",
            "any survey you take personally",
        ):
            assert told in page

    def test_the_personal_page_says_nothing_about_an_organization(self, client, bob):
        grant_personal(bob)
        page = html(client, START)
        assert "Acme" not in page and "The admins of" not in page
        assert "your answers are visible to you and to Accelerare" in page

    def test_opening_the_page_costs_nothing(self, client, bob, licensed):
        page = html(client, ACME)
        assert 'name="took_before"' in page and "Start the survey" in page
        assert not Response.objects.exists() and not hasattr(licensed, "response")

    def test_posting_starts_an_attempt_for_the_organization(self, client, bob, member, licensed):
        personal = grant_personal(bob)
        response = client.post(ACME, {"took_before": "yes", "took_before_via": "company"})
        draft = Response.objects.get()
        assert response.status_code == 302 and response.url == f"/survey/{draft.pk}/"
        assert draft.membership == member and draft.entitlement == licensed
        assert draft.took_before is True and draft.took_before_via == "company"
        assert not hasattr(fresh(personal), "response")  # the personal licence is untouched
        assert FunnelEvent.objects.filter(kind="survey_started").count() == 1

    def test_posting_again_resumes_the_same_attempt(self, client, bob, member):
        client.post(ACME, {"took_before": "yes", "took_before_via": "individual"})
        grant(member)  # must not be consumed
        client.post(ACME, {"took_before": "no"})
        draft = Response.objects.get()
        assert draft.took_before is False and draft.took_before_via == ""
        page = html(client, ACME)
        assert "You have already started" in page and "Save and continue" in page

    def test_an_invalid_answer_costs_nothing(self, client, bob):
        response = client.post(ACME, {"took_before": "yes", "took_before_via": ""})
        assert response.status_code == 200
        assert "Please say how you took it." in response.content.decode()
        assert not Response.objects.exists()

    def test_once_page_1_is_locked_it_offers_continue(self, client, bob):
        client.post(ACME, {"took_before": "no"})
        draft = services.complete_page(answer_page_one(Response.objects.get()), 1)
        page = html(client, ACME)
        assert "Your survey is in progress" in page and 'name="took_before"' not in page
        assert f'href="/survey/{draft.pk}/"' in page
        again = client.post(ACME, {"took_before": "yes", "took_before_via": "other"})
        assert again.status_code == 302 and again.url == ACME
        assert fresh(draft).took_before is False

    def test_an_attempt_with_no_self_report_goes_back_to_its_own_start_page(
        self, client, bob, member
    ):
        draft = services.start_response(bob, member)
        assert client.get(url("resume", draft)).url == ACME
        assert client.get(url("page", draft, 1)).url == ACME
        # And a personal one still goes to the personal start page.
        grant_personal(bob)
        personal = services.start_response(bob)
        assert client.get(url("resume", personal)).url == START

    def test_the_two_start_pages_keep_their_attempts_apart(self, client, bob, member):
        grant_personal(bob)
        client.post(START, {"took_before": "no"})
        client.post(ACME, {"took_before": "yes", "took_before_via": "other"})
        personal = Response.objects.get(membership__isnull=True)
        for_acme = Response.objects.get(membership=member)
        assert personal.took_before is False and for_acme.took_before is True
        # Each page resumes its own.
        services.complete_page(answer_page_one(for_acme), 1)
        assert "You have already started" in html(client, START)
        assert "Your survey is in progress" in html(client, ACME)

    def test_the_organizations_name_is_shown_as_text_never_as_markup(self, client, bob, acme):
        Enterprise.objects.filter(pk=acme[0].pk).update(name="<script>alert(1)</script>")
        page = html(client, ACME)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page

    def test_the_page_shows_no_statement(self, client, bob):
        assert "Question 1" not in html(client, ACME)
        client.post(ACME, {"took_before": "no"})
        assert "Question 1" not in html(client, ACME)


# --- the pages of the attempt --------------------------------------------------


@pytest.mark.django_db
class TestTheAttemptsPages:
    def test_they_say_which_organization_it_is_for(self, client, bob, member):
        grant(member)
        draft = services.save_self_report(services.start_response(bob, member), False)
        assert "Page 1 of 5 · for Acme" in html(client, url("page", draft, 1))
        draft = finish_pages(draft)
        assert "You are taking this survey for Acme." in html(client, url("review", draft))

    def test_a_personal_attempt_names_no_organization(self, client, bob):
        grant_personal(bob)
        draft = services.save_self_report(services.start_response(bob), False)
        page = html(client, url("page", draft, 1))
        assert "Page 1 of 5" in page and "Acme" not in page
        assert "Acme" not in html(client, url("review", finish_pages(draft)))

    def test_a_draft_that_vanishes_mid_request_lands_somewhere_sensible(
        self, client, bob, member, monkeypatch
    ):
        def vanished(*args, **kwargs):
            raise Response.DoesNotExist

        grant(member)
        for_acme = services.save_self_report(services.start_response(bob, member), False)
        grant_personal(bob)
        personal = services.save_self_report(services.start_response(bob), False)
        monkeypatch.setattr(response_views.services, "complete_page", vanished)
        # The organization's start page may be closed to them by now, so "My surveys".
        assert client.post(url("next_page", for_acme), {"page": "1"}).url == HISTORY
        assert client.post(url("next_page", personal), {"page": "1"}).url == START


def finish_pages(response):
    """Answer and lock every page, a page at a time as the Next button does, without submitting."""
    pages = {}
    for question in Question.objects.filter(survey_version=response.survey_version):
        pages.setdefault(services.page_of(question.position), {})[question.pk] = 3
    for page in sorted(pages):
        response = services.complete_page(response, page, pages[page])
    return response


# --- "My surveys" --------------------------------------------------------------


@pytest.mark.django_db
class TestHistory:
    def test_without_an_organization_the_page_is_as_before(self, client, db):
        carol = verified_account("carol@example.com")
        client.force_login(carol)
        grant_personal(carol)
        page = html(client, HISTORY)
        assert "You have 1 unused licence<" in page and f'href="{START}"' in page
        # No box labels: they only appear once the person has an organization.
        # (The header's "Organizations" link is on every page.)
        assert ">Organization<" not in page and ">Personal<" not in page
        assert "/survey/start/acme/" not in page

    def test_a_member_with_no_licence_is_told_one_is_needed(self, client, bob):
        page = html(client, HISTORY)
        assert "Free account" in page and "No unused licence for Acme" in page
        assert ACME not in page and START not in page

    def test_an_unused_licence_for_the_organization_offers_start_there(self, client, bob, member):
        grant(member)
        page = html(client, HISTORY)
        assert "You have 1 unused licence for Acme" in page and f'href="{ACME}"' in page
        assert "Free account" in page and f'href="{START}"' not in page
        grant(member)
        assert "You have 2 unused licences for Acme" in html(client, HISTORY)

    def test_an_open_attempt_offers_continue_and_says_who_it_is_for(self, client, bob, member):
        grant(member)
        draft = services.save_self_report(services.start_response(bob, member), False)
        page = html(client, HISTORY)
        assert "Your survey for Acme is in progress" in page
        assert page.count(f'href="{url("resume", draft)}"') == 2  # the box and the row
        assert "For Acme · In progress · Tier 2" in page

    def test_each_context_gets_its_own_box(self, client, bob, member):
        grant_personal(bob)
        personal = services.start_response(bob)
        grant(member)
        for_acme = services.start_response(bob, member)
        page = html(client, HISTORY)
        assert "Your survey is in progress" in page
        assert "Your survey for Acme is in progress" in page
        assert url("resume", personal) in page and url("resume", for_acme) in page
        assert "Personal · In progress · Tier 1" in page
        assert "For Acme · In progress · Tier 2" in page

    def test_a_submitted_survey_links_to_its_result_with_its_context(self, client, bob, member):
        grant(member, 3)
        done = finish(services.start_response(bob, member))
        page = html(client, HISTORY)
        assert "For Acme · Submitted · Tier 3" in page and url("result", done) in page
        assert "No unused licence for Acme" in page

    def test_organizations_are_listed_by_name(self, client, bob, member):
        zeta, _ = org_with_admin("Zeta")
        grant(Membership.objects.create(enterprise=zeta, account=bob))
        grant(member)
        page = html(client, HISTORY)
        assert page.index("unused licence for Acme") < page.index("unused licence for Zeta")
        assert 'href="/survey/start/zeta/"' in page

    def test_after_leaving_the_history_stays_but_the_box_goes(self, client, acme, member, bob):
        grant(member)
        done = finish(services.start_response(bob, member))
        grant(member)
        orgs.deactivate_membership(member, by=acme[1])
        page = html(client, HISTORY)
        assert "For Acme · Submitted · Tier 2" in page and url("result", done) in page
        assert "licence for Acme" not in page and ACME not in page
        assert client.get(url("result", done)).status_code == 200

    def test_it_never_shows_another_members_attempts(self, client, acme, bob):
        carol = new_member(acme[0], "carol@example.com")
        grant(carol)
        hers = services.start_response(carol.account, carol)
        page = html(client, HISTORY)
        assert url("resume", hers) not in page and "In progress" not in page
        assert "You have not taken the survey yet" in page


# --- the result ----------------------------------------------------------------


@pytest.mark.django_db
class TestResult:
    def test_it_says_who_the_survey_was_taken_for(self, client, bob, member):
        grant(member)
        for_acme = finish(services.start_response(bob, member))
        grant_personal(bob)
        personal = finish(services.start_response(bob))
        assert "For Acme" in html(client, url("result", for_acme))
        page = html(client, url("result", personal))
        assert "Personally" in page and "Acme" not in page

    def test_another_members_result_is_not_found(self, client, acme, bob):
        carol = new_member(acme[0], "carol@example.com")
        grant(carol)
        hers = finish(services.start_response(carol.account, carol))
        assert client.get(url("result", hers)).status_code == 404
        # Not for the organization's admin either: the admin pages come later
        # and never go through a member's own result page.
        client.force_login(acme[1].account)
        assert client.get(url("result", hers)).status_code == 404
