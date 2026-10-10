"""
Erasing an account: the one place that decides what is deleted and what is kept.

Two outcomes, chosen by the data and never by the caller:

* No completed (submitted) survey: nothing here is worth keeping, so the account
  is deleted outright, with its contacts, licences, unfinished attempt and
  person.
* A completed survey: the person is stripped and the survey kept. The email,
  phone and login are removed, the password is made unusable and the results stay
  with no link to a person. `anonymised_at` marks it, so reports can count
  former members (historical totals) apart from current ones.

An account that has acted in the admin is also stripped rather than deleted:
deleting it would cascade away the admin history of what it did.

What is stripped is listed in `_anonymise` and nowhere else, so a lawyer's "also
remove X" is a one-line change. Demographics (age, gender, company) belong on
Person, not here: erasing clears the account and its contacts and leaves the
person alone.

Both outcomes are irreversible, run in one transaction, and scrub the admin
history of the person's email so it does not outlive the erasure. This module
reaches responses and licences through their reverse relations ("responses",
"entitlements") so accounts never imports the apps that depend on it.
"""

from dataclasses import dataclass

from allauth.account.models import EmailAddress
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Account, ContactPoint

DELETE = "delete"
ANONYMISE = "anonymise"


@dataclass(frozen=True)
class Plan:
    action: str  # DELETE or ANONYMISE
    summary: str  # plain words, shown on the confirmation page


def _explain(account: Account, action: str, submitted: int) -> str:
    licences = account.person.entitlements.count() if account.person_id else 0
    if action == DELETE:
        return (
            "This account has no completed survey, so it will be permanently deleted: "
            f"its email and phone, its {licences} licence(s) and any unfinished attempt. "
            "This cannot be undone."
        )
    why = (
        f"This account has {submitted} completed survey(s), so it will not be deleted."
        if submitted
        else "This account has used the admin, so it will not be deleted (that would erase "
        "the history of what it did)."
    )
    return (
        f"{why} Its email, phone number and login will be removed and its results kept "
        "with no link to a person. Any unfinished attempt is deleted and unused licences "
        "are revoked. This cannot be undone."
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
    submitted = account.responses.filter(status="submitted").count()
    has_admin_history = LogEntry.objects.filter(user=account).exists()
    action = ANONYMISE if submitted or has_admin_history else DELETE
    return Plan(action, _explain(account, action, submitted))


def erase_account(account: Account, by: Account | None = None) -> Plan:
    """Do what plan_erasure says, all or nothing. Returns the plan that ran."""
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        plan = plan_erasure(account, by)
        _scrub_history(account)
        _end_sessions(account)
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
    account.delete()  # takes the contacts and allauth's email rows with it
    if person is not None and not shared:
        person.delete()


def _anonymise(account: Account) -> None:
    """The strip list: email, phone, name (no name field exists yet), login."""
    now = timezone.now()
    account.responses.filter(status="draft").delete()
    # The unfinished attempt is gone, so its licence is unused; nobody can use it.
    # Same effect as entitlements.services.revoke, which accounts must not import.
    if account.person_id:
        account.person.entitlements.filter(revoked_at__isnull=True, response__isnull=True).update(
            revoked_at=now
        )
    account.contact_points.all().delete()
    EmailAddress.objects.filter(user=account).delete()

    account.email = f"erased-{account.pk}@erased.invalid"
    account.set_unusable_password()
    account.is_active = False
    account.is_staff = False
    account.is_superuser = False
    account.groups.clear()
    account.user_permissions.clear()
    account.personal_email_prompt_dismissed_at = None
    account.anonymised_at = now
    account.save()
