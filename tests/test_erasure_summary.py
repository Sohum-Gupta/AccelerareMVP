"""
Milestone 6, PR 3: erasing an account records what was removed, as numbers.

Before this, the audit log said that an account was erased and by whom, but
not what went. Now `plan_erasure` counts what will be removed and what will be
kept; the page that asks first shows those counts, and `erase_account` writes
the same counts into its audit row, with what the three listening apps say
they removed (possible duplicates, the box under "Yes", an invite's address).
Never a name: "2 contacts", not which.

Each count is checked here against what really happened in the database, by
counting the tables before and after.
"""
# ruff: noqa: F811  (pytest fixtures imported by their own name)

import json

import pytest
from django.utils import timezone

from apps.accounts import erasure
from apps.accounts.models import Account, ContactPoint
from apps.audit.models import AuditLog
from apps.enterprises import services as orgs
from apps.enterprises.models import Invite, Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.matching import services as matching
from apps.matching.models import MatchCandidate
from apps.responses.models import Response
from apps.results.models import Result

from .orgs import add_member, org_with_admin
from .test_erasure import bob, complete, erase_url, root, start  # noqa: F401
from .test_matching import ann, ann2, give, pair, take  # noqa: F401
from .test_profile import second_email, verified_account
from .test_response_context import fresh, grant


def measured():
    """What is in the tables that an erasure touches."""
    return {
        "contacts": ContactPoint.objects.count(),
        "drafts": Response.objects.filter(status="draft").count(),
        "submitted": Response.objects.filter(status="submitted").count(),
        "licences": Entitlement.objects.count(),
        "licences_in_force": Entitlement.objects.filter(revoked_at__isnull=True).count(),
        "memberships": Membership.objects.count(),
        "active_memberships": Membership.objects.filter(status="active").count(),
    }


def erased_row():
    return AuditLog.objects.get(action="account.erased")


def erase(account, by=None):
    """Erase, and return (the plan made beforehand, what the tables lost, the audit row's facts)."""
    before = measured()
    planned = erasure.plan_erasure(fresh(account), by)
    erasure.erase_account(fresh(account), by=by)
    after = measured()
    lost = {name: before[name] - after[name] for name in before}
    return planned, lost, erased_row().detail


@pytest.fixture
def acme(db):
    return org_with_admin("Acme")


@pytest.mark.django_db
class TestAnAccountThatIsDeleted:
    def test_the_counts_are_what_the_tables_lost(self, bob, acme):
        """Bob: two emails and a phone, a spare licence, an unfinished survey, one membership."""
        second_email(bob, "bob.personal@example.com")
        start(bob)
        licences.grant_individual(bob.person, 1, "manual", None)
        member = orgs.redeem_code(orgs.create_code(acme[1], 5).code, bob)
        grant(member, 2)

        plan, lost, _facts = erase(bob)
        assert plan.action == erasure.DELETE
        assert plan.counts == {
            "contacts_removed": 3,
            "unfinished_surveys_removed": 1,
            "surveys_kept": 0,
            "licences_removed": 3,
            "memberships_removed": 1,
        }
        assert lost["contacts"] == 3 and lost["drafts"] == 1 and lost["submitted"] == 0
        assert lost["licences"] == 3 and lost["memberships"] == 1

    def test_the_audit_row_holds_the_same_counts(self, bob, root):
        start(bob)
        plan, _lost, facts = erase(bob, by=root)
        assert facts == {
            "results_kept": False,
            **plan.counts,
            "possible_duplicates_removed": 0,
            "match_boxes_emptied": 0,
            "invite_addresses_removed": 0,
        }
        assert facts["unfinished_surveys_removed"] == 1 and facts["licences_removed"] == 1
        assert erased_row().actor == root

    def test_a_membership_that_was_already_deactivated_is_deleted_and_counted_too(self, bob, acme):
        orgs.redeem_code(orgs.create_code(acme[1], 5).code, bob)
        _globex, globex_admin = org_with_admin("Globex")
        left = orgs.redeem_code(orgs.create_code(globex_admin, 5).code, bob)
        orgs.deactivate_membership(left, by=globex_admin)
        plan, lost, _facts = erase(bob)
        assert plan.action == erasure.DELETE
        assert plan.counts["memberships_removed"] == 2 and lost["memberships"] == 2

    def test_an_account_with_nothing_has_only_its_contacts_to_lose(self, bob):
        plan, lost, _facts = erase(bob)
        assert plan.counts == {
            "contacts_removed": 2,
            "unfinished_surveys_removed": 0,
            "surveys_kept": 0,
            "licences_removed": 0,
            "memberships_removed": 0,
        }
        assert lost["contacts"] == 2 and lost["licences"] == 0


@pytest.mark.django_db
class TestAnAccountWhoseSurveyIsKept:
    def test_the_counts_are_what_the_tables_lost(self, bob, acme):
        """
        Bob submitted one survey personally; has a spare licence, a licence that
        was already revoked, and an unfinished survey for Acme; and has left
        another organization.
        """
        complete(bob)
        licences.grant_individual(bob.person, 1, "manual", None)
        licences.revoke(licences.grant_individual(bob.person, 1, "manual", None))
        member = orgs.redeem_code(orgs.create_code(acme[1], 5).code, bob)
        Response.objects.create(
            account=bob,
            survey_version=Response.objects.get().survey_version,
            entitlement=grant(member, 2),
            membership=member,
        )
        _globex, globex_admin = org_with_admin("Globex")
        left = orgs.redeem_code(orgs.create_code(globex_admin, 5).code, bob)
        orgs.deactivate_membership(left, by=globex_admin)

        plan, lost, facts = erase(bob)
        assert plan.action == erasure.ANONYMISE
        assert plan.counts == {
            "contacts_removed": 2,
            "unfinished_surveys_removed": 1,
            "surveys_kept": 1,
            # The spare one and the one under the unfinished survey. Not the
            # one already revoked, and not the one the kept survey used.
            "licences_revoked": 2,
            # Acme. Globex had already deactivated him.
            "memberships_deactivated": 1,
        }
        assert lost["contacts"] == 2 and lost["drafts"] == 1 and lost["submitted"] == 0
        assert lost["licences"] == 0 and lost["licences_in_force"] == 2
        assert lost["memberships"] == 0 and lost["active_memberships"] == 1
        assert facts["results_kept"] is True and facts["licences_revoked"] == 2

    def test_a_licence_the_kept_survey_used_is_never_counted_or_revoked(self, bob):
        used = complete(bob).entitlement
        plan, lost, _facts = erase(bob)
        assert plan.counts["licences_revoked"] == 0 and lost["licences_in_force"] == 0
        assert fresh(used).revoked_at is None

    def test_an_account_kept_only_because_it_used_the_admin(self, bob, root):
        from .test_erasure import log

        log(bob, root, "something")
        plan, lost, _facts = erase(bob)
        assert plan.action == erasure.ANONYMISE
        assert plan.counts["surveys_kept"] == 0 and lost["contacts"] == 2


@pytest.mark.django_db
class TestALinkedLogin:
    def test_stripping_one_counts_only_its_own_unused_licences(self, pair, ann, ann2, root):
        give(ann)
        take(ann)
        give(ann)
        give(ann2)
        matching.confirm(pair, root)
        plan, lost, facts = erase(ann)
        assert plan.action == erasure.ANONYMISE and plan.other_login_kept
        assert plan.counts["licences_revoked"] == 1 and lost["licences_in_force"] == 1
        assert facts["other_login_kept"] is True
        assert "Another login is linked to this person" in plan.summary

    def test_deleting_one_removes_none_of_the_shared_licences(self, pair, ann, ann2, root):
        give(ann)
        give(ann2)
        matching.confirm(pair, root)
        plan, lost, facts = erase(ann)
        assert plan.action == erasure.DELETE and plan.other_login_kept
        assert plan.counts["licences_removed"] == 0 and lost["licences"] == 0
        assert "its 0 licence(s)" in plan.summary
        assert facts["other_login_kept"] is True

    def test_an_account_on_its_own_says_nothing_about_another_login(self, bob):
        plan, _lost, facts = erase(bob)
        assert not plan.other_login_kept
        assert "other_login_kept" not in facts and "Another login" not in plan.summary

    def test_a_linked_login_that_was_itself_erased_does_not_count(self, pair, ann, ann2, root):
        for account in (ann, ann2):
            give(account)
            take(account)
        matching.confirm(pair, root)
        erasure.erase_account(fresh(ann2))
        AuditLog.objects.filter(action="account.erased").delete()
        plan, _lost, facts = erase(ann)
        assert not plan.other_login_kept and "other_login_kept" not in facts


@pytest.mark.django_db
class TestWhatTheOtherAppsRemoved:
    def test_a_possible_duplicate(self, pair, ann):
        assert MatchCandidate.objects.count() == 1
        _plan, _lost, facts = erase(ann)
        assert facts["possible_duplicates_removed"] == 1
        assert not MatchCandidate.objects.exists()

    def test_the_box_under_yes(self, bob):
        complete(bob, took_before=True, took_before_via="other", match_hint="typed by the person")
        _plan, _lost, facts = erase(bob)
        assert facts["match_boxes_emptied"] == 1
        assert Response.objects.get().match_hint == ""

    def test_an_invite_sent_to_their_address(self, bob, acme):
        orgs.invite_by_email(acme[1], "bob@example.com")
        orgs.invite_by_email(acme[1], "someone.else@example.com")
        _plan, _lost, facts = erase(bob)
        assert facts["invite_addresses_removed"] == 1
        assert sorted(Invite.objects.values_list("email", flat=True)) == [
            "",
            "someone.else@example.com",
        ]

    def test_an_invite_whose_address_had_already_gone_is_not_counted(self, bob, acme):
        """Bob joined by an invite, and its address was emptied before he is erased."""
        invite, _sent = orgs.invite_by_email(acme[1], "bob.work@example.com")
        add_member(acme[0], bob, joined_via_invite=invite)
        Invite.objects.filter(pk=invite.pk).update(email="")
        _plan, _lost, facts = erase(bob)
        assert facts["invite_addresses_removed"] == 0

    def test_the_invite_they_joined_with_is_counted_whatever_its_address(self, bob, acme):
        invite, _sent = orgs.invite_by_email(acme[1], "bob.work@example.com")
        add_member(acme[0], bob, joined_via_invite=invite)
        _plan, _lost, facts = erase(bob)
        assert facts["invite_addresses_removed"] == 1
        assert Invite.objects.get(pk=invite.pk).email == ""


@pytest.mark.django_db
class TestTheRecordNamesNobody:
    def test_no_name_address_or_number_of_theirs(self, acme, root):
        carol = verified_account("carol.unusual@example.com")
        Account.objects.filter(pk=carol.pk).update(full_name="Carol Unusualname")
        complete(carol)
        orgs.invite_by_email(acme[1], "carol.unusual@example.com")
        erasure.erase_account(carol, by=root)
        stored = json.dumps(
            list(AuditLog.objects.filter(action="account.erased").values()), default=str
        )
        for word in ("carol", "Carol", "Unusualname", "@", "9876543210", "Acme"):
            assert word not in stored, word

    def test_every_fact_is_a_number_or_yes_or_no(self, bob):
        complete(bob)
        _plan, _lost, facts = erase(bob)
        assert all(isinstance(value, (bool, int)) for value in facts.values())

    def test_an_erasure_that_is_refused_counts_nothing_and_records_nothing(self, root):
        with pytest.raises(Exception, match="own account"):
            erasure.erase_account(root, by=root)
        assert not AuditLog.objects.filter(action="account.erased").exists()


@pytest.mark.django_db
class TestAResultFollowsItsSurvey:
    def result_of(self, response):
        return Result.objects.create(
            response=response, algorithm_version="test", payload={}, computed_at=timezone.now()
        )

    def test_it_is_kept_with_a_submitted_survey(self, bob):
        result = self.result_of(complete(bob))
        erasure.erase_account(bob)
        assert Result.objects.filter(pk=result.pk).exists()

    def test_it_goes_with_an_unfinished_one(self, bob):
        complete(bob)
        self.result_of(start(bob))
        erasure.erase_account(bob)
        assert not Result.objects.exists()

    def test_and_with_an_account_that_is_deleted_outright(self, bob):
        self.result_of(start(bob))
        assert erasure.erase_account(bob).action == erasure.DELETE
        assert not Result.objects.exists()


@pytest.mark.django_db
class TestThePageThatAsksFirst:
    def test_it_lists_the_counts_in_plain_words(self, client, root, bob):
        complete(bob)
        start(bob)
        page = client.get(erase_url(bob)).content.decode()
        table = page.split("data-erase-counts")[1].split("</table>")[0]
        for label, number in [
            ("Email addresses and phone numbers removed", 2),
            ("Unfinished surveys deleted", 1),
            ("Submitted surveys kept, with no link to a person", 1),
            ("Unused licences revoked", 1),
            ("Organization memberships deactivated", 0),
        ]:
            assert f'<th scope="row">{label}</th><td>{number}</td>' in table, label
        assert "Licences deleted" not in table
        assert "also kept in the audit log" in table

    def test_for_an_account_that_will_be_deleted_it_says_deleted(self, client, root, bob):
        start(bob)
        table = client.get(erase_url(bob)).content.decode().split("data-erase-counts")[1]
        assert '<th scope="row">Licences deleted</th><td>1</td>' in table
        assert '<th scope="row">Organization memberships deleted</th><td>0</td>' in table
        assert "revoked" not in table.split("</table>")[0]

    def test_looking_at_the_page_erases_and_records_nothing(self, client, root, bob):
        assert client.get(erase_url(bob)).status_code == 200
        assert Account.objects.filter(pk=bob.pk, anonymised_at__isnull=True).exists()
        assert not AuditLog.objects.filter(action="account.erased").exists()

    def test_erasing_from_the_page_records_the_counts_and_who(self, client, root, bob):
        complete(bob)
        client.post(erase_url(bob), {"email": "bob@example.com", "reason": "deletion request"})
        row = erased_row()
        assert row.actor == root and row.target_id == str(bob.pk)
        assert row.detail["contacts_removed"] == 2 and row.detail["surveys_kept"] == 1

    def test_every_count_has_a_plain_label(self, bob):
        for prepare in (lambda: None, lambda: complete(bob)):
            prepare()
            plan = erasure.plan_erasure(bob)
            assert [number for _label, number in plan.lines()] == list(plan.counts.values())
            assert all(label and "_" not in label for label, _number in plan.lines())
