"""
Milestone 2, PR 3: the Response model and its database rules, how it changes
licence access, and the two admin levels (superuser sees everything; support
staff see which questions are answered, never the values).
"""

import pytest
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Account
from apps.entitlements import services as licences
from apps.responses import services
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME
from apps.survey.services import current_version

from .test_admin_and_guard import root  # noqa: F401  (fixture)
from .test_profile import verified_account
from .test_verification import PASSWORD


@pytest.fixture
def bob(db):
    return verified_account("bob@example.com")


def licence(account, tier=1):
    return licences.grant_individual(account.person, tier, "manual", None)


def start(account, entitlement=None, **extra):
    return Response.objects.create(
        account=account,
        survey_version=current_version(),
        entitlement=entitlement or licence(account),
        **extra,
    )


def submit_row(response):
    response.status = "submitted"
    response.submitted_at = timezone.now()
    response.save()


@pytest.mark.django_db
class TestDatabaseRules:
    def test_one_licence_is_one_attempt(self, bob):
        lic = licence(bob)
        start(bob, lic)
        with pytest.raises(IntegrityError), transaction.atomic():
            start(bob, lic)

    def test_one_open_draft_per_account(self, bob):
        start(bob)
        with pytest.raises(IntegrityError), transaction.atomic():
            start(bob)

    def test_a_submitted_response_does_not_block_a_new_draft(self, bob):
        submit_row(start(bob))
        assert start(bob).status == "draft"

    def test_two_accounts_can_each_have_a_draft(self, bob):
        start(bob)
        start(verified_account("carol@example.com"))

    def test_draft_with_a_submit_time_is_refused(self, bob):
        with pytest.raises(IntegrityError), transaction.atomic():
            start(bob, submitted_at=timezone.now())

    def test_submitted_without_a_submit_time_is_refused(self, bob):
        with pytest.raises(IntegrityError), transaction.atomic():
            start(bob, status="submitted")

    def test_defaults(self, bob):
        response = start(bob)
        assert response.answers == {} and response.pages_completed == 0
        assert response.took_before is None and response.possible_repeat is False

    def test_the_via_answer_needs_a_yes(self, bob):
        with pytest.raises(IntegrityError), transaction.atomic():
            start(bob, took_before=False, took_before_via="company")
        with pytest.raises(IntegrityError), transaction.atomic():
            start(bob, took_before=None, took_before_via="other")
        assert start(bob, took_before=True, took_before_via="other").took_before_via == "other"

    def test_a_response_blocks_deleting_what_it_points_at(self, bob):
        from django.db.models import ProtectedError

        response = start(bob)
        for target in (response.entitlement, response.survey_version, bob):
            with pytest.raises(ProtectedError):
                target.delete()


@pytest.mark.django_db
class TestLicenceAccess:
    def test_a_used_licence_is_no_longer_unused(self, bob):
        first = licence(bob, 1)
        second = licence(bob, 3)
        assert licences.unused_licence(bob) == first
        start(bob, first)
        assert licences.unused_licence(bob) == second
        start_after = Response.objects.get()
        submit_row(start_after)
        start(bob, second)
        assert licences.unused_licence(bob) is None

    def test_an_open_draft_counts_as_access(self, bob):
        start(bob)
        assert licences.unused_licence(bob) is None
        assert licences.has_survey_access(bob)

    def test_after_submitting_access_needs_another_licence(self, bob):
        response = start(bob)
        submit_row(response)
        assert not licences.has_survey_access(bob)
        licence(bob)
        assert licences.has_survey_access(bob)

    def test_revoking_the_licence_removes_the_draft_and_the_access(self, bob):
        response = start(bob)
        licences.revoke(response.entitlement)
        assert not Response.objects.filter(pk=response.pk).exists()
        assert not licences.has_survey_access(bob)


@pytest.mark.django_db
def test_answered_positions_reports_positions_not_values(bob):
    questions = list(current_version().questions.all())
    response = start(bob, answers={str(questions[0].pk): 4, str(questions[2].pk): 1})
    assert services.answered_positions(response) == [1, 3]


# --- the admin -------------------------------------------------------------------


@pytest.fixture
def support(client, db):
    account = Account.objects.create_user("support@example.com", PASSWORD)
    account.is_staff = True
    account.save()
    account.groups.add(Group.objects.get(name=GROUP_NAME))
    client.force_login(account)
    return account


def answered_response(bob):
    questions = list(current_version().questions.all())
    answers = {str(q.pk): 3 for q in questions[:14]}
    return start(bob, answers=answers, took_before=True, took_before_via="company")


@pytest.mark.django_db
class TestAdmin:
    def test_superuser_sees_the_answers_read_only(self, client, root, bob):  # noqa: F811
        response = answered_response(bob)
        url = f"/admin/responses/response/{response.pk}/change/"
        page = client.get(url).content.decode()
        assert "Took before via" in page and "&quot;" in page  # self-report and answers JSON
        assert 'name="answers"' not in page  # as text, not an editable box
        assert client.post(url, {"status": "submitted"}).status_code == 403

    def test_support_staff_see_which_questions_but_not_the_values(self, client, support, bob):
        response = answered_response(bob)
        assert client.get("/admin/responses/response/").status_code == 200
        page = client.get(f"/admin/responses/response/{response.pk}/change/").content.decode()
        assert "14 of 25: 1, 2, 3" in page
        assert "Took before" not in page and "Answers" not in page
        assert "{&quot;" not in page  # no answers JSON rendered

    def test_support_staff_cannot_find_a_response_through_its_answers(self, client, support, bob):
        answered_response(bob)
        page = client.get("/admin/responses/response/", {"q": "company"}).content.decode()
        assert "bob@example.com" not in page

    def test_nobody_can_add_or_delete(self, client, root, bob):  # noqa: F811
        response = start(bob)
        assert client.get("/admin/responses/response/add/").status_code == 403
        url = f"/admin/responses/response/{response.pk}/delete/"
        assert client.post(url, {"post": "yes"}).status_code == 403
        assert Response.objects.count() == 1

    def test_plain_staff_without_the_group_sees_nothing(self, client, bob):
        account = Account.objects.create_user("plain@example.com", PASSWORD)
        account.is_staff = True
        account.save()
        client.force_login(account)
        assert client.get("/admin/responses/response/").status_code == 403


@pytest.mark.django_db
class TestSupportStaffGroup:
    def test_support_staff_can_grant_and_revoke_licences(self, client, support, bob):
        response = client.post(
            "/admin/entitlements/entitlement/add/",
            {"account": bob.pk, "tier": 1, "source": "manual"},
        )
        assert response.status_code == 302
        grant = licences.unused_licence(bob)
        assert grant.granted_by == support
        client.post(
            "/admin/entitlements/entitlement/",
            {"action": "revoke_selected", "_selected_action": [grant.pk]},
        )
        grant.refresh_from_db()
        assert grant.revoked_at is not None

    def test_support_staff_can_read_questions_and_accounts_but_not_change_them(
        self, client, support, bob
    ):
        assert client.get("/admin/survey/question/").status_code == 200
        assert client.get("/admin/accounts/account/").status_code == 200
        url = f"/admin/accounts/account/{bob.pk}/change/"
        assert client.post(url, {"is_superuser": "on"}).status_code in (302, 403)
        bob.refresh_from_db()
        assert not bob.is_superuser

    def test_the_group_has_exactly_the_agreed_permissions(self, db):
        granted = set(
            Group.objects.get(name=GROUP_NAME).permissions.values_list("codename", flat=True)
        )
        assert granted == {
            "add_entitlement",
            "change_entitlement",
            "view_entitlement",
            "view_response",
            "view_account",
            "view_person",
            "view_contactpoint",
            "view_surveyversion",
            "view_question",
            "view_funnelevent",
        }
