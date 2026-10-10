"""
Milestone 2, PR 3b: erasing an account. No completed survey means a hard delete;
a completed survey means the identity is stripped and the results kept. Either
way the email is free to sign up with again and no trace of it is left behind.
"""

import pytest
from allauth.account.models import EmailAddress
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts import erasure, services
from apps.accounts.models import Account, ContactPoint, Person
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.responses.models import Response
from apps.survey.services import current_version

from .test_profile import verified_account
from .test_verification import PASSWORD


@pytest.fixture
def bob(db):
    return verified_account("bob@example.com")


def start(account, **extra):
    return Response.objects.create(
        account=account,
        survey_version=current_version(),
        entitlement=licences.grant_individual(account.person, 2, "manual", None),
        **extra,
    )


def complete(account, **extra):
    return start(account, status="submitted", submitted_at=timezone.now(), **extra)


def log(user, obj, text):
    LogEntry.objects.create(
        user=user,
        content_type=ContentType.objects.get_for_model(obj),
        object_id=str(obj.pk),
        object_repr=text,
        action_flag=CHANGE,
    )


@pytest.mark.django_db
class TestHardDelete:
    def test_removes_everything_and_the_email_can_be_used_again(self, bob):
        person_id = bob.person_id
        start(bob)  # an unfinished attempt and its licence
        spare = licences.grant_individual(bob.person, 1, "manual", None)
        assert erasure.plan_erasure(bob).action == erasure.DELETE
        assert erasure.erase_account(bob).action == erasure.DELETE
        assert not Account.objects.filter(pk=bob.pk).exists()
        assert not Person.objects.filter(pk=person_id).exists()
        assert not ContactPoint.objects.exists()
        assert not EmailAddress.objects.filter(email="bob@example.com").exists()
        assert not Response.objects.exists()
        assert not Entitlement.objects.filter(pk=spare.pk).exists()
        again = services.register("bob@example.com", "+919876543210", None, PASSWORD)
        assert again.pk != bob.pk and again.person_id != person_id

    def test_a_shared_person_and_its_licences_are_kept(self, bob):
        licence = licences.grant_individual(bob.person, 1, "manual", None)
        other = Account.objects.create_user("other@example.com", PASSWORD)
        Account.objects.filter(pk=other.pk).update(person=bob.person)
        erasure.erase_account(bob)
        assert Person.objects.filter(pk=bob.person_id).exists()
        assert Entitlement.objects.filter(pk=licence.pk).exists()

    def test_nothing_changes_if_it_fails_halfway(self, bob, monkeypatch):
        start(bob)
        monkeypatch.setattr(Account, "delete", lambda self, *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            erasure.erase_account(bob)
        assert Account.objects.filter(pk=bob.pk).exists()
        assert Response.objects.count() == 1 and Entitlement.objects.count() == 1


@pytest.mark.django_db
class TestAnonymise:
    def test_strips_the_identity_and_keeps_the_survey(self, bob):
        done = complete(bob, answers={"1": 3}, took_before=True, took_before_where="old@acme.com")
        draft_licence = licences.grant_individual(bob.person, 1, "manual", None)
        assert erasure.plan_erasure(bob).action == erasure.ANONYMISE
        erasure.erase_account(bob)

        bob.refresh_from_db()
        assert bob.email == f"erased-{bob.pk}@erased.invalid"
        assert bob.anonymised_at is not None
        assert not bob.is_active and not bob.has_usable_password()
        assert not bob.contact_points.exists()
        assert not EmailAddress.objects.filter(user=bob).exists()

        done.refresh_from_db()
        assert done.status == "submitted" and done.answers == {"1": 3}
        assert done.took_before is True and done.took_before_where == ""
        assert done.entitlement.tier == 2 and done.entitlement.revoked_at is None
        draft_licence.refresh_from_db()
        assert draft_licence.revoked_at is not None  # unused, so nobody can use it
        assert Person.objects.filter(pk=bob.person_id).exists()

    def test_deletes_an_unfinished_attempt_but_not_the_finished_one(self, bob):
        complete(bob)
        start(bob)
        erasure.erase_account(bob)
        assert list(Response.objects.values_list("status", flat=True)) == ["submitted"]

    def test_the_email_is_free_again_and_the_new_account_is_separate(self, bob):
        complete(bob)
        erasure.erase_account(bob)
        again = services.register("bob@example.com", "+919876543210", None, PASSWORD)
        assert again.pk != bob.pk and again.person_id != bob.person_id
        assert not again.responses.exists()

    def test_the_erased_account_cannot_log_in(self, client, bob):
        complete(bob)
        erasure.erase_account(bob)
        assert not client.login(email="bob@example.com", password=PASSWORD)
        assert not client.login(email=f"erased-{bob.pk}@erased.invalid", password=PASSWORD)

    def test_ends_their_sessions(self, client, bob):
        complete(bob)
        client.force_login(bob)
        assert Session.objects.count() == 1
        erasure.erase_account(bob)
        assert Session.objects.count() == 0

    def test_an_account_that_has_used_the_admin_is_stripped_not_deleted(self, bob):
        log(bob, bob, "some object")  # bob acted in the admin
        assert erasure.erase_account(bob).action == erasure.ANONYMISE
        assert Account.objects.filter(pk=bob.pk).exists()
        assert LogEntry.objects.filter(user=bob).count() == 1

    def test_staff_rights_are_removed(self, bob):
        complete(bob)
        Account.objects.filter(pk=bob.pk).update(is_staff=True)
        bob.refresh_from_db()
        erasure.erase_account(bob)
        bob.refresh_from_db()
        assert not bob.is_staff and not bob.is_superuser


@pytest.mark.django_db
class TestHistoryIsScrubbed:
    def test_the_email_does_not_survive_in_the_admin_history(self, bob):
        staff = Account.objects.create_superuser("root@example.com", PASSWORD)
        contact = bob.contact_points.get(kind="email")
        log(staff, bob, "bob@example.com")
        log(staff, contact, "bob@example.com")
        erasure.erase_account(bob)
        reprs = list(LogEntry.objects.values_list("object_repr", flat=True))
        assert "bob@example.com" not in reprs
        assert f"Account #{bob.pk}" in reprs and "Erased contact" in reprs


@pytest.mark.django_db
class TestRefusals:
    def test_not_twice(self, bob):
        complete(bob)
        erasure.erase_account(bob)
        bob.refresh_from_db()
        with pytest.raises(ValidationError, match="already been erased"):
            erasure.erase_account(bob)

    def test_not_yourself(self, bob):
        with pytest.raises(ValidationError, match="own account"):
            erasure.erase_account(bob, by=bob)
        assert Account.objects.filter(pk=bob.pk).exists()

    def test_not_the_last_active_superuser(self, db):
        only = Account.objects.create_superuser("root@example.com", PASSWORD)
        with pytest.raises(ValidationError, match="last active superuser"):
            erasure.erase_account(only)
        second = Account.objects.create_superuser("root2@example.com", PASSWORD)
        erasure.erase_account(only, by=second)
        assert Account.objects.filter(pk=second.pk).exists()
