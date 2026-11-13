"""
Erasing an account: the one place that decides what is deleted and what is kept.

Two outcomes, chosen by the data and never by the caller:

* No completed (submitted) survey: nothing here is worth keeping, so the account
  is deleted outright, with its contacts, licences, unfinished attempt,
  organization memberships and person.
* A completed survey: the person is stripped and the survey kept. The email,
  phone, name and login are removed, the password is made unusable and the results stay
  with no link to a person. `anonymised_at` marks it, so reports can count
  former members (historical totals) apart from current ones. Its organization
  memberships are kept but deactivated (the founder's choice of 2026-11-12, for
  the privacy lawyer to confirm): the organization still sees that a former
  member took the survey, shown as "Erased member".

An account that has acted in the admin is also stripped rather than deleted:
deleting it would cascade away the admin history of what it did.

What is stripped is listed in `_anonymise` and nowhere else, so a lawyer's "also
remove X" is a one-line change. Demographics (age, gender, company) belong on
Person, not here: erasing clears the account and its contacts and leaves the
person alone.

Both outcomes are irreversible, run in one transaction, and scrub the admin
history of the person's email so it does not outlive the erasure. This module
reaches responses, licences and memberships through their reverse relations
("responses", "entitlements", "memberships") so accounts never imports the apps
that depend on it. For the same reason a status is written here as plain text
("draft", "active"), not as the other app's constant. What no relation reaches
(an invite that was sent to the person's address) is handled by the app that
owns it, which listens for the `account_erasing` signal below.
"""

from dataclasses import dataclass

from allauth.account.models import EmailAddress
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from apps.audit import services as audit

from .models import Account, ContactPoint

# Sent inside the erasure's transaction, before anything is removed, with
# `account` and `emails` (the addresses the account has verified). It is how an
# app that depends on accounts removes its own copies of the person's address
# (an organization's invites, say) without accounts having to import that app.
# A receiver that raises stops the erasure and undoes all of it.
account_erasing = Signal()

DELETE = "delete"
ANONYMISE = "anonymise"


@dataclass(frozen=True)
class Plan:
    action: str  # DELETE or ANONYMISE
    summary: str  # plain words, shown on the confirmation page


def _explain(account: Account, action: str, submitted: int) -> str:
    licences = account.person.entitlements.count() if account.person_id else 0
    memberships = account.memberships.count()
    for membership in account.memberships.all():
        licences += membership.entitlements.count()
    if action == DELETE:
        return (
            "This account has no completed survey, so it will be permanently deleted: "
            f"its email, phone and name, its {licences} licence(s), its membership of "
            f"{memberships} organization(s) and any unfinished attempt. "
            "This cannot be undone."
        )
    why = (
        f"This account has {submitted} completed survey(s), so it will not be deleted."
        if submitted
        else "This account has used the admin, so it will not be deleted (that would erase "
        "the history of what it did)."
    )
    return (
        f"{why} Its email, phone number, name and login will be removed and its results kept "
        "with no link to a person. Any unfinished attempt is deleted and unused licences "
        f"are revoked. Its membership of {memberships} organization(s) is deactivated and "
        'shown there as "Erased member". This cannot be undone.'
    )


def plan_erasure(account: Account, by: Account | None = None) -> Plan:
    """What erase_account would do, or ValidationError saying why it must not."""
    if account.anonymised_at is not None:
        raise ValidationError("This account has already been erased.")
    if by is not None and by.pk == account.pk:
        raise ValidationError("You cannot erase your own account.")
    if (
        account.is_superuser
        and account.is_active
        and not Account.objects.filter(is_superuser=True, is_active=True)
        .exclude(pk=account.pk)
        .exists()
    ):
        raise ValidationError("This is the last active superuser, so it cannot be erased.")
    stranded = _organizations_left_without_an_admin(account)
    if stranded:
        raise ValidationError(
            f"This account is the only admin of {', '.join(stranded)}, which still has "
            "other members. Make another member an admin there first, then erase."
        )
    submitted = account.responses.filter(status="submitted").count()
    has_admin_history = LogEntry.objects.filter(user=account).exists()
    action = ANONYMISE if submitted or has_admin_history else DELETE
    return Plan(action, _explain(account, action, submitted))


def _organizations_left_without_an_admin(account: Account) -> list[str]:
    """
    Names of the organizations where this account is the only active admin while
    other people are still active members. Erasing it would leave them with
    nobody who can invite, deactivate or see who took the survey, so staff are
    asked to appoint another admin first (founder's decision, 2026-11-12). An
    organization with nobody else in it does not block: it is simply left empty.
    """
    names = []
    admin_of = account.memberships.filter(role="admin", status="active").select_related(
        "enterprise"
    )
    for membership in admin_of:
        others = membership.enterprise.memberships.filter(status="active").exclude(pk=membership.pk)
        if others.exists() and not others.filter(role="admin").exists():
            names.append(membership.enterprise.name)
    return names


def erase_account(account: Account, by: Account | None = None) -> Plan:
    """Do what plan_erasure says, all or nothing. Returns the plan that ran."""
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        # Lock the memberships before anything of theirs is touched. An admin
        # deactivating this person locks the membership and then deletes its
        # unfinished attempt; taking the locks in the same order here (membership,
        # then responses) means the two wait for each other instead of deadlocking.
        list(account.memberships.select_for_update())
        plan = plan_erasure(account, by)
        emails = list(
            account.contact_points.filter(
                kind=ContactPoint.Kind.EMAIL, verified_at__isnull=False
            ).values_list("value_normalised", flat=True)
        )
        account_erasing.send(sender=Account, account=account, emails=emails)
        _scrub_history(account)
        _end_sessions(account)
        # Who erased which account, by number. The row outlives the account:
        # it holds nothing that says who the person was.
        audit.record(by, "account.erased", account, results_kept=plan.action == ANONYMISE)
        if plan.action == ANONYMISE:
            _anonymise(account)
        else:
            _hard_delete(account)
    return plan


def _scrub_history(account: Account) -> None:
    """The admin history keeps the email as the object's name; replace it."""
    accounts = ContentType.objects.get_for_model(Account)
    contacts = ContentType.objects.get_for_model(ContactPoint)
    LogEntry.objects.filter(content_type=accounts, object_id=str(account.pk)).update(
        object_repr=f"Account #{account.pk}"
    )
    contact_ids = [str(pk) for pk in account.contact_points.values_list("pk", flat=True)]
    LogEntry.objects.filter(content_type=contacts, object_id__in=contact_ids).update(
        object_repr="Erased contact"
    )


def _end_sessions(account: Account) -> None:
    # Sessions are keyed by a random string, so finding one person's means
    # decoding the live ones. Fine at this size; revisit if sessions get huge.
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.get_decoded().get("_auth_user_id") == str(account.pk):
            session.delete()


def _hard_delete(account: Account) -> None:
    person = account.person
    # If another login shares the person (a Milestone 5 merge), keep the person
    # and their licences for it and remove only this login.
    shared = person is not None and person.accounts.exclude(pk=account.pk).exists()
    account.responses.all().delete()  # before licences: a response protects its licence
    if person is not None and not shared:
        person.entitlements.all().delete()
    # A membership protects its account, and a licence protects its membership,
    # so they go in that order. Nothing of this person is worth keeping (their
    # licences are all unused: the unfinished attempts went above), so the
    # organization keeps no trace of them either.
    for membership in account.memberships.all():
        membership.entitlements.all().delete()
    account.memberships.all().delete()
    account.delete()  # takes the contacts and allauth's email rows with it
    if person is not None and not shared:
        person.delete()


def _anonymise(account: Account) -> None:
    """The strip list: email, phone, name, login."""
    now = timezone.now()
    account.responses.filter(status="draft").delete()
    # The unfinished attempt is gone, so its licence is unused; nobody can use it.
    # Same effect as entitlements.services.revoke, which accounts must not import.
    if account.person_id:
        unused = account.person.entitlements.filter(revoked_at__isnull=True, response__isnull=True)
        others = account.person.accounts.exclude(pk=account.pk)
        if others.filter(anonymised_at__isnull=True).exists():
            # Another login is linked to this person and shares its licences
            # (a Milestone 5 link). Only the ones that were this login's go;
            # the other login keeps its own.
            unused = unused.filter(granted_to=account)
        unused.update(revoked_at=now)
    # The same for the unused licences of their memberships: an erased member
    # never comes back, so nobody can use them.
    for membership in account.memberships.all():
        membership.entitlements.filter(revoked_at__isnull=True, response__isnull=True).update(
            revoked_at=now
        )
    # The membership link is kept, deactivated: the person has left, and the
    # organization keeps its count of who took the survey.
    # Like any deactivation, it also ends being an admin.
    account.memberships.filter(status="active").update(
        status="deactivated", deactivated_at=now, role="member"
    )
    account.contact_points.all().delete()
    EmailAddress.objects.filter(user=account).delete()

    account.email = f"erased-{account.pk}@erased.invalid"
    account.full_name = ""
    account.set_unusable_password()
    account.is_active = False
    account.is_staff = False
    account.is_superuser = False
    account.groups.clear()
    account.user_permissions.clear()
    account.personal_email_prompt_dismissed_at = None
    account.anonymised_at = now
    account.save()
