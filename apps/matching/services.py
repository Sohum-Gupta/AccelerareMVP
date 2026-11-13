"""
Every write about possible duplicates goes through here.

Looking (run_for_account) never changes an account. It runs the rules and
stores each pair it finds for a superuser to look at. Only `confirm` links two
logins, and only a superuser can call it. `reject` closes a pair for good, and
`unlink` undoes a link.

What a link is. Each account has a person, and personal licences belong to
the person. Linking moves the newer login onto the older login's person, and
the newer login's personal licences with it, so the two logins share one stock
of personal licences. Nothing else changes: each login keeps its own password,
its own surveys and its own memberships. Undoing the link gives the newer
login its own person back, with the licences that are its own.

A person has at most two logins in this version: a login that is already
linked to another cannot be linked to a third. That keeps "undo" exact.
"""

from django.db import transaction
from django.db.models import Q
from django.dispatch import Signal
from django.utils import timezone

from apps.accounts.models import Account, Person
from apps.audit import services as audit
from apps.entitlements.models import Entitlement

from . import rules
from .models import MatchCandidate

Status = MatchCandidate.Status

# Sent, inside the transaction, when two logins have been linked or a link has
# been undone: `accounts` is the two account numbers. Apps that depend on this
# one listen (the responses app re-marks possible repeats); this app must not
# import them.
people_changed = Signal()


class Refused(Exception):
    """The plain-words reason something about a possible duplicate cannot be done."""


SUPERUSERS_ONLY = "Only a superuser can decide a possible duplicate."
NOT_WAITING = "This possible duplicate has already been decided."
NOT_LINKED = "These two accounts are not linked, so there is no link to undo."
GONE = "One of these accounts has been erased or switched off, so they cannot be linked."
ALREADY_LINKED = "These two accounts are already linked to each other."
THIRD_LOGIN = (
    "Account #{number} is already linked to another account. A person can have two "
    "linked logins at most, so undo that link first if this pair is the better match."
)


# --- looking ----------------------------------------------------------------------------------


def run_for_account(account):
    """
    Look for accounts that may belong to the same person as this one, and
    store each pair found as a possible duplicate. Returns the pairs that are
    waiting for a decision because of it.

    Safe to run any number of times: a pair is stored once, however often and
    by however many rules it is found. A pair that a superuser has already
    decided is left exactly as it is. Nothing about either account changes.
    """
    account = _live(Account.objects.filter(pk=getattr(account, "pk", account))).first()
    if account is None:
        return []
    found = {}
    for name, _, rule in rules.RULES:
        for other in rule(account):
            found.setdefault(other, set()).add(name)
    others = _live(Account.objects.filter(pk__in=found)).exclude(pk=account.pk)
    if account.person_id is not None:
        others = others.exclude(person_id=account.person_id)  # already one person
    waiting = []
    for other in others.values_list("pk", flat=True):
        candidate = _flag(account.pk, other, found[other])
        if candidate is not None:
            waiting.append(candidate)
    return waiting


def _flag(first, second, names):
    """Store the pair, or add to what an undecided pair has in common. None if it was decided."""
    lower, higher = sorted((first, second))
    with transaction.atomic():
        candidate, created = MatchCandidate.objects.get_or_create(
            account_a_id=lower, account_b_id=higher, defaults={"signals": sorted(names)}
        )
        if created:
            return candidate
        candidate = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
        if candidate.status != Status.FLAGGED:
            return None
        both = sorted(set(candidate.signals) | set(names))
        if both != candidate.signals:
            candidate.signals = both
            candidate.save(update_fields=["signals"])
        return candidate


def _live(accounts):
    """Accounts that are someone's working login: not switched off, not erased."""
    return accounts.filter(is_active=True, anonymised_at__isnull=True)


# --- deciding ---------------------------------------------------------------------------------


def link_preview(candidate):
    """
    What `confirm` would do, for the page that asks first: a dict with `can`,
    and either `why_not` or `kept` and `moved` (the two accounts) and
    `licences` (how many personal licences the moved login brings with it).
    Nothing is locked or changed.
    """
    try:
        kept, moved = _who_moves(candidate.account_a, candidate.account_b)
    except Refused as error:
        return {"can": False, "why_not": str(error)}
    licences = Entitlement.objects.filter(person_id=moved.person_id).count()
    return {"can": True, "kept": kept, "moved": moved, "licences": licences}


def confirm(candidate, by):
    """
    A superuser says the two accounts are the same person: link them. The
    newer login moves onto the older login's person and brings its personal
    licences, so both logins can use either's. Returns the candidate.

    Allowed for a pair that is waiting, and for one whose link was undone
    (the superuser changed their mind). Refused if either account has been
    erased or switched off, or is already linked to another account.
    """
    _check_superuser(by)
    with transaction.atomic():
        candidate = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
        if candidate.status not in (Status.FLAGGED, Status.UNLINKED):
            raise Refused(NOT_WAITING)
        kept, moved = _who_moves(*_locked_accounts(candidate))
        _lock_people(kept.person_id, moved.person_id)
        old_person = moved.person_id
        licences = list(
            Entitlement.objects.filter(person_id=old_person).values_list("pk", flat=True)
        )
        Entitlement.objects.filter(pk__in=licences).update(person_id=kept.person_id)
        Account.objects.filter(pk=moved.pk).update(person_id=kept.person_id)
        Person.objects.filter(pk=old_person).update(merged_into_id=kept.person_id)
        candidate.status = Status.CONFIRMED
        candidate.old_person_id = old_person
        _decided(candidate, by, "old_person")
        audit.record(
            by, "accounts.linked", candidate, kept=kept.pk, moved=moved.pk, licences=licences
        )
        people_changed.send(sender=MatchCandidate, accounts=[kept.pk, moved.pk])
        return candidate


def reject(candidate, by):
    """A superuser says they are different people. The pair is closed and never raised again."""
    _check_superuser(by)
    with transaction.atomic():
        candidate = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
        if candidate.status != Status.FLAGGED:
            raise Refused(NOT_WAITING)
        candidate.status = Status.REJECTED
        _decided(candidate, by)
        audit.record(by, "possible_duplicate.rejected", candidate)
        return candidate


def unlink_preview(candidate):
    """What `unlink` would do, for the page that asks first. Nothing is locked or changed."""
    kept, moved = candidate.account_a, candidate.account_b
    if candidate.status != Status.CONFIRMED or kept.person_id != moved.person_id:
        return {"can": False, "why_not": NOT_LINKED}
    going = _goes_with(moved, kept.person_id).count()
    staying = Entitlement.objects.filter(person_id=kept.person_id).count() - going
    return {"can": True, "kept": kept, "moved": moved, "going": going, "staying": staying}


def unlink(candidate, by):
    """
    A superuser undoes a link. The newer login gets its own person back, and
    with it: every personal licence it has used, and every unused one that was
    granted to it or bought by it, before the link or since. Everything else
    stays with the older login. Returns the candidate.
    """
    _check_superuser(by)
    with transaction.atomic():
        candidate = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
        if candidate.status != Status.CONFIRMED:
            raise Refused(NOT_LINKED)
        kept, moved = _locked_accounts(candidate, live_only=False)
        if kept.person_id != moved.person_id:
            raise Refused(NOT_LINKED)
        _lock_people(kept.person_id, candidate.old_person_id)
        # Its old person, if that row is still there and nobody else's; else a new one.
        own = Person.objects.filter(pk=candidate.old_person_id, accounts__isnull=True).first()
        if own is None:
            own = Person.objects.create()
        licences = list(_goes_with(moved, kept.person_id).values_list("pk", flat=True))
        Entitlement.objects.filter(pk__in=licences).update(person_id=own.pk)
        Account.objects.filter(pk=moved.pk).update(person_id=own.pk)
        Person.objects.filter(pk=own.pk).update(merged_into=None)
        candidate.status = Status.UNLINKED
        _decided(candidate, by)
        audit.record(
            by, "accounts.unlinked", candidate, kept=kept.pk, moved=moved.pk, licences=licences
        )
        people_changed.send(sender=MatchCandidate, accounts=[kept.pk, moved.pk])
        return candidate


def forget(account):
    """Remove every possible duplicate this account is part of (it is being erased)."""
    MatchCandidate.objects.filter(account_a=account).delete()
    MatchCandidate.objects.filter(account_b=account).delete()


# --- helpers ----------------------------------------------------------------------------------


def _check_superuser(by):
    if by is None or not by.is_active or not by.is_superuser:
        raise Refused(SUPERUSERS_ONLY)


def _decided(candidate, by, *more_fields):
    candidate.resolved_by = by
    candidate.resolved_at = timezone.now()
    candidate.save(update_fields=["status", "resolved_by", "resolved_at", *more_fields])


def _locked_accounts(candidate, live_only=True):
    """The pair's two accounts as they are now, locked, lower number first."""
    pair = [candidate.account_a_id, candidate.account_b_id]
    locked = list(Account.objects.select_for_update().filter(pk__in=pair).order_by("pk"))
    if len(locked) != 2 or (live_only and not all(_is_live(account) for account in locked)):
        raise Refused(GONE)
    return locked


def _lock_people(*people):
    list(Person.objects.select_for_update().filter(pk__in=[p for p in people if p]).order_by("pk"))


def _is_live(account):
    return account.is_active and account.anonymised_at is None and account.person_id is not None


def _who_moves(older, newer):
    """(the login that keeps its person, the login that moves onto it), or Refused."""
    if not (_is_live(older) and _is_live(newer)):
        raise Refused(GONE)
    if older.person_id == newer.person_id:
        raise Refused(ALREADY_LINKED)
    for account in (older, newer):
        others = _live(Account.objects.filter(person_id=account.person_id)).exclude(pk=account.pk)
        if others.exists():
            raise Refused(THIRD_LOGIN.format(number=account.pk))
    return older, newer


def _goes_with(moved, shared_person):
    """
    The personal licences that leave with a login when its link is undone:
    those it has used (whoever they were granted to: its survey is on them),
    and the unused ones that were granted to it or bought by it. A licence the
    other login has used stays where it is.
    """
    return Entitlement.objects.filter(person_id=shared_person).filter(
        Q(response__account=moved) | Q(granted_to=moved, response__isnull=True)
    )
