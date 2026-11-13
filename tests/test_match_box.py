"""
Milestone 5, PR 5: the optional box under "Yes, I have taken this survey before".

The rule. After answering yes, the person may type an email address or phone
number they used when they took the survey before. It is optional and nothing
depends on it. It is used once, in the background, to look for their other
account. If that address or number belongs to another account, the pair
becomes a possible duplicate for a superuser, like any other. Then the box is
emptied, whether or not it found anyone. Only a superuser can ever see it, and
no organization ever does. Erasing the person removes it.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts import services as accounts
from apps.accounts.models import Account, ContactPoint
from apps.audit.models import AuditLog
from apps.enterprises import services as orgs
from apps.entitlements import services as licences
from apps.jobs import services as jobs
from apps.jobs.models import Job
from apps.matching import rules, services
from apps.matching.models import MatchCandidate
from apps.responses import services as surveys
from apps.responses.models import Response
from apps.responses.signals import GROUP_NAME

from .orgs import add_member, org_with_admin
from .test_matching import OTHER_PHONE, PASSWORD, PHONE, give, someone
from .test_response_services import finish_pages

START = "/survey/start/"
OLD = "ann.old@example.com"


@pytest.fixture
def old(db):
    """The account the person took the survey with before."""
    return someone(OLD, PHONE)


@pytest.fixture
def ann(old, client):
    """The same person's new account: another address, another phone, a licence, logged in."""
    account = someone("ann@example.com", OTHER_PHONE)
    give(account)
    client.force_login(account)
    return account


def typed(account, hint, took_before=True):
    """The person starts the survey, says yes (or no) and types this into the box."""
    response = surveys.start_response(account)
    return surveys.save_self_report(response, took_before, "other" if took_before else "", hint)


def box(response):
    return Response.objects.get(pk=response.pk).match_hint


def looks_queued(account):
    return Job.objects.filter(
        kind=accounts.LOOK_FOR_DUPLICATES, payload={"account_id": account.pk}
    ).count()


# --- what is found ----------------------------------------------------------------------------


@pytest.mark.django_db
class TestWhatTheBoxFinds:
    def test_an_address_that_belongs_to_another_account_makes_a_possible_duplicate(self, old, ann):
        response = typed(ann, OLD)
        assert box(response) == OLD and looks_queued(ann) == 1
        assert not MatchCandidate.objects.exists()  # nothing until the worker runs
        jobs.run_due()
        pair = MatchCandidate.objects.get()
        assert (pair.account_a, pair.account_b) == (old, ann)
        assert pair.status == "flagged" and pair.signals == ["match_box"]

    def test_however_the_address_was_typed(self, old, ann):
        typed(ann, "  Ann.OLD@Example.com ")
        assert len(services.run_for_account(ann)) == 1

    def test_a_phone_number_that_belongs_to_another_account_does_too(self, old, ann):
        typed(ann, PHONE)
        (pair,) = services.run_for_account(ann)
        assert (pair.account_a, pair.account_b) == (old, ann) and pair.signals == ["match_box"]

    def test_a_number_typed_the_local_way_is_read_as_one_from_their_own_country(self, old, ann):
        typed(ann, "098765 43210")  # the same number, as someone in India writes it
        assert len(services.run_for_account(ann)) == 1

    def test_an_address_nobody_has_proven_is_theirs_finds_nothing(self, old, ann):
        """Anyone can list an address; only a verified one says whose it is."""
        ContactPoint.objects.filter(account=old, kind="email").update(verified_at=None)
        typed(ann, OLD)
        assert services.run_for_account(ann) == []

    def test_a_second_verified_address_of_the_other_account_counts(self, old, ann):
        contact = accounts.add_email(old, "ann.second@example.com")
        ContactPoint.objects.filter(pk=contact.pk).update(verified_at=timezone.now())
        typed(ann, "ann.second@example.com")
        assert len(services.run_for_account(ann)) == 1

    def test_their_own_address_or_number_finds_nothing(self, old, ann):
        typed(ann, "ann@example.com")
        assert services.run_for_account(ann) == []
        Response.objects.update(match_hint=OTHER_PHONE)
        assert services.run_for_account(ann) == []

    def test_something_that_is_neither_finds_nothing_and_breaks_nothing(self, old, ann):
        for junk in ("my old work email", "12", "@", "+", "x" * 254):
            Response.objects.all().delete()
            response = typed(ann, junk)
            assert services.run_for_account(ann) == []
            assert box(response) == ""
        assert rules.owners_of("not a number", ann) == set()

    def test_an_erased_or_switched_off_account_is_not_found(self, old, ann):
        Account.objects.filter(pk=old.pk).update(is_active=False)
        typed(ann, OLD)
        assert services.run_for_account(ann) == []

    def test_a_pair_already_found_another_way_gains_the_reason(self, old, ann):
        accounts.change_phone(ann, PHONE, None)
        (first,) = services.run_for_account(ann)
        assert first.signals == ["same_phone"]
        typed(ann, OLD)
        (again,) = services.run_for_account(ann)
        assert again.pk == first.pk and again.signals == ["match_box", "same_phone"]

    def test_the_superuser_reads_why_in_plain_words(self, client, old, ann):
        typed(ann, OLD)
        (pair,) = services.run_for_account(ann)
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        page = client.get(
            reverse("admin:matching_matchcandidate_change", args=[pair.pk])
        ).content.decode()
        assert "typed an email address or phone number that belongs to the other" in page

    def test_the_pair_holds_the_name_of_the_rule_and_never_what_was_typed(self, old, ann):
        typed(ann, OLD)
        (pair,) = services.run_for_account(ann)
        assert "@" not in json.dumps([pair.signals, str(pair)])

    def test_looking_never_links_anyone(self, old, ann):
        typed(ann, OLD)
        services.run_for_account(ann)
        assert Account.objects.get(pk=ann.pk).person_id != Account.objects.get(pk=old.pk).person_id


# --- used once, then gone ---------------------------------------------------------------------


@pytest.mark.django_db
class TestUsedOnceThenGone:
    def test_the_box_is_emptied_when_it_found_someone(self, old, ann):
        response = typed(ann, OLD)
        services.run_for_account(ann)
        assert box(response) == "" and MatchCandidate.objects.count() == 1

    def test_and_when_it_found_nobody(self, old, ann):
        response = typed(ann, "nobody@example.com")
        assert services.run_for_account(ann) == [] and box(response) == ""

    def test_the_rest_of_the_answer_stays(self, old, ann):
        response = typed(ann, OLD)
        services.run_for_account(ann)
        response.refresh_from_db()
        assert response.took_before is True and response.took_before_via == "other"

    def test_something_typed_after_the_look_began_is_kept_for_the_next_one(
        self, old, ann, monkeypatch
    ):
        """The person changes the box while the worker is half way through."""
        response = typed(ann, "nobody@example.com")
        the_rules, real = rules.RULES, rules.RULES[-1][2]

        def retype_then_look(account):
            found = real(account)
            Response.objects.filter(pk=response.pk).update(match_hint=OLD)
            return found

        monkeypatch.setattr(rules, "RULES", [("match_box", "", retype_then_look)])
        assert services.run_for_account(ann) == [] and box(response) == OLD
        monkeypatch.setattr(rules, "RULES", the_rules)
        assert len(services.run_for_account(ann)) == 1 and box(response) == ""

    def test_the_job_empties_it_and_a_second_run_changes_nothing(self, old, ann):
        response = typed(ann, OLD)
        jobs.run_due()
        accounts.look_for_duplicates_later(ann)
        jobs.run_due()
        assert box(response) == "" and MatchCandidate.objects.count() == 1

    def test_nothing_about_it_reaches_the_audit_log_or_the_queue(self, old, ann):
        typed(ann, OLD)
        jobs.run_due()
        stored = json.dumps(
            [list(Job.objects.values_list("payload", "last_error"))]
            + [list(AuditLog.objects.values_list("detail", flat=True))]
        )
        assert "@" not in stored and "ann.old" not in stored


# --- saving it --------------------------------------------------------------------------------


@pytest.mark.django_db
class TestSavingIt:
    def test_it_is_optional_and_an_empty_box_queues_no_look(self, ann):
        response = typed(ann, "")
        assert box(response) == "" and looks_queued(ann) == 0

    def test_it_is_only_kept_with_a_yes(self, ann):
        response = typed(ann, OLD, took_before=False)
        assert box(response) == "" and looks_queued(ann) == 0

    def test_changing_the_answer_to_no_empties_it(self, ann):
        response = typed(ann, OLD)
        surveys.save_self_report(response, False)
        assert box(response) == ""

    def test_spaces_are_tidied_and_too_much_is_refused(self, ann):
        response = typed(ann, "  +91  98765   43210 ")
        assert box(response) == "+91 98765 43210"
        with pytest.raises(surveys.Invalid, match="too long"):
            surveys.save_self_report(response, True, "other", "x" * 255)
        assert box(response) == "+91 98765 43210"

    def test_the_database_refuses_a_box_without_a_yes(self, ann):
        from django.db import IntegrityError, transaction

        response = typed(ann, "", took_before=False)
        with pytest.raises(IntegrityError), transaction.atomic():
            Response.objects.filter(pk=response.pk).update(match_hint=OLD)

    def test_it_cannot_be_changed_once_page_1_is_locked(self, ann):
        response = typed(ann, "")
        finish_pages(response, 1)
        with pytest.raises(surveys.Locked):
            surveys.save_self_report(response, True, "other", OLD)
        assert box(response) == ""

    def test_a_survey_can_be_finished_with_something_still_in_the_box(self, old, ann):
        """The worker is down: the survey still submits, and the look happens when it is back."""
        response = typed(ann, OLD)
        response = surveys.submit(finish_pages(response, surveys.page_count(response)))
        assert response.status == "submitted" and box(response) == OLD
        jobs.run_due()
        assert box(response) == "" and MatchCandidate.objects.count() == 1


# --- the page ---------------------------------------------------------------------------------


@pytest.mark.django_db
class TestThePage:
    def test_the_box_is_on_the_start_page_and_says_what_happens_to_it(self, client, ann):
        html = client.get(START).content.decode()
        assert 'name="match_hint"' in html
        assert "An email address or phone number you used then (optional)" in html
        assert "We use it once" in html and "then delete it" in html
        # Under "Yes", with the "how" question: the page script shows both together.
        via = html.index("data-self-report-via")
        assert via < html.index('name="took_before_via"') < html.index('name="match_hint"')

    def test_yes_with_the_box_filled_starts_the_survey_and_queues_the_look(self, client, old, ann):
        answer = {"took_before": "yes", "took_before_via": "individual", "match_hint": OLD}
        response = client.post(START, answer)
        draft = Response.objects.get()
        assert response.status_code == 302 and draft.match_hint == OLD
        assert looks_queued(ann) == 1
        jobs.run_due()
        assert box(draft) == "" and MatchCandidate.objects.get().signals == ["match_box"]

    def test_yes_with_the_box_empty_is_fine(self, client, ann):
        client.post(START, {"took_before": "yes", "took_before_via": "individual"})
        assert Response.objects.get().match_hint == "" and looks_queued(ann) == 0

    def test_no_ignores_whatever_is_in_the_box(self, client, ann):
        client.post(START, {"took_before": "no", "match_hint": OLD})
        assert Response.objects.get().match_hint == ""

    def test_too_much_in_the_box_is_an_error_on_the_box(self, client, ann):
        answer = {"took_before": "yes", "took_before_via": "other", "match_hint": "x" * 300}
        html = client.post(START, answer).content.decode()
        assert "at most 254 characters" in html and not Response.objects.exists()

    def test_coming_back_before_the_worker_has_run_shows_what_was_typed(self, client, ann):
        client.post(START, {"took_before": "yes", "took_before_via": "other", "match_hint": OLD})
        assert f'value="{OLD}"' in client.get(START).content.decode()
        jobs.run_due()
        assert f'value="{OLD}"' not in client.get(START).content.decode()


# --- who can see it ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWhoSeesIt:
    def test_a_superuser_sees_it_on_the_response_and_support_staff_do_not(self, client, ann):
        response = typed(ann, OLD)
        address = reverse("admin:responses_response_change", args=[response.pk])
        client.force_login(Account.objects.create_superuser("root@example.com", PASSWORD))
        assert OLD in client.get(address).content.decode()
        support = Account.objects.create_user("support@example.com", PASSWORD, is_staff=True)
        support.groups.add(Group.objects.get(name=GROUP_NAME))
        client.force_login(support)
        page = client.get(address)
        assert page.status_code == 200 and OLD not in page.content.decode()

    def test_an_organizations_admin_never_sees_it(self, client, old, db):
        enterprise, admin = org_with_admin("Acme")
        orgs.set_seat_pool(enterprise, 2, 1)
        ann = someone("ann@example.com", OTHER_PHONE)
        member = add_member(enterprise, ann)
        licences.assign_seat(admin, member, 2)
        response = surveys.start_response(ann, member)
        response = surveys.save_self_report(response, True, "other", OLD)
        response = surveys.submit(finish_pages(response, surveys.page_count(response)))
        assert box(response) == OLD  # the worker has not run: the worst case
        client.force_login(admin.account)
        for address in (
            reverse("organization_responses", args=[enterprise.slug]),
            reverse("organization_response", args=[enterprise.slug, response.pk]),
        ):
            page = client.get(address)
            assert page.status_code == 200 and OLD not in page.content.decode()

    def test_the_person_themselves_is_not_shown_it_again_on_their_result(self, client, old, ann):
        response = typed(ann, OLD)
        response = surveys.submit(finish_pages(response, surveys.page_count(response)))
        for name in ("responses:result", "responses:history"):
            args = [response.pk] if name.endswith("result") else []
            assert OLD not in client.get(reverse(name, args=args)).content.decode()


# --- erasing ----------------------------------------------------------------------------------


@pytest.mark.django_db
class TestErasing:
    def test_erasing_the_person_empties_the_box_on_the_surveys_that_are_kept(self, old, ann):
        response = typed(ann, OLD)
        surveys.submit(finish_pages(response, surveys.page_count(response)))
        assert erasure.erase_account(ann).action == erasure.ANONYMISE
        assert box(response) == ""

    def test_a_job_still_queued_for_an_erased_account_does_nothing(self, old, ann):
        response = typed(ann, OLD)
        surveys.submit(finish_pages(response, surveys.page_count(response)))
        erasure.erase_account(ann)
        jobs.run_due()
        assert not MatchCandidate.objects.exists()
        assert not Job.objects.exclude(status="done").exists()


def test_the_three_rules_are_the_ones_the_plan_names():
    assert [name for name, _, _ in rules.RULES] == ["same_phone", "same_name", "match_box"]
    assert set(rules.WORDS) == {"same_phone", "same_name", "match_box"}
