"""
Every write to a response goes through here. Views stay thin and the rules live
in one place, so the web pages, the tests and any later admin tool enforce the
same thing.

The rules: a licence is one attempt; five statements a page; answers are taken
only for the page being answered; Next locks a page for good and needs all five
answered; submit needs every page locked and every
statement answered; a submitted response never changes. The self-report
("taken before?") is answered before page 1 and cannot change after it locks.

Concurrency: each function opens a transaction and re-reads the response with
SELECT ... FOR UPDATE, so two tabs (or a double click) queue up instead of
writing over each other; the caller's copy is treated as stale and the fresh
row is returned. start_response locks the account row (so it queues behind an
erasure), then the owner of the licences: the person row for a personal attempt
(so two logins sharing one person cannot both consume the same licence), or the
membership row for an organization's (so a start and a deactivation of that
member take turns). Then it locks that context's licences (so a revoke cannot
slip in between choosing a licence and using it). The database constraints (one
licence one attempt, one open draft per account and context) are the backstop.

Context: an attempt is personal or for one organization, and the licence
decides which. start_response is told the context (a membership, or none for
personal), consumes a licence of that context only, and copies the licence's
membership onto the response, so the two can never disagree.

A write the rules do not allow raises Refused or one of its subclasses with a
plain-words message; the views turn it into a 409. A funnel event is recorded
inside the same transaction as the thing it counts, so a refusal or a rollback
leaves no event.
"""

import math

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts import services as accounts
from apps.accounts.models import Account, Person
from apps.enterprises.models import Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.funnel import services as funnel
from apps.jobs import services as jobs
from apps.results import services as results
from apps.survey.models import Question
from apps.survey.services import PAGE_SIZE, current_version

from .models import Response

MATCH_HINT_MAX_LENGTH = 254  # as long as an email address may be; the column's length


class Refused(Exception):
    """A write the rules do not allow. str(error) is plain words for the person."""


class NoLicence(Refused):
    """Nothing to consume: no unused licence and no open draft."""


class Locked(Refused):
    """Already done: the response is submitted, or that page is locked."""


class Incomplete(Refused):
    """Something is still unanswered."""


class Invalid(Refused):
    """A value that makes no sense here: wrong type, out of range, wrong question."""


# --- reads ---------------------------------------------------------------------


def answered_positions(response):
    """Positions of the questions this response has an answer for, never the values."""
    ids = [int(key) for key in response.answers]
    return list(
        Question.objects.filter(survey_version=response.survey_version_id, id__in=ids)
        .order_by("position")
        .values_list("position", flat=True)
    )


def page_of(position):
    """Which page a statement at this position is on (pages count from 1)."""
    return (position - 1) // PAGE_SIZE + 1


def page_count(response):
    """How many pages this response's survey version has."""
    return math.ceil(_questions(response).count() / PAGE_SIZE)


# --- writes --------------------------------------------------------------------


def start_response(account, membership=None):
    """
    The account's open draft in this context, or a new one on that context's
    oldest unused licence. The context is personal (membership None) or one
    organization (the account's own active membership of it). Raises NoLicence
    when there is neither a draft nor a licence, and Refused for a membership
    that is someone else's or has been deactivated.
    """
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        if not account.is_active or account.anonymised_at is not None or account.person_id is None:
            raise Refused("This account cannot take the survey.")
        if membership is None:
            Person.objects.select_for_update().get(pk=account.person_id)
            owner = {"person_id": account.person_id, "membership__isnull": True}
            no_licence = "You need a licence to take the survey."
        else:
            # A plain single-table lock, then the checks on the row as it is now:
            # a deactivation that got here first is seen, and one that arrives
            # later waits and then deletes the draft made below.
            membership = Membership.objects.select_for_update().filter(pk=membership.pk).first()
            if membership is None or membership.account_id != account.pk:
                raise Refused("You are not a member of that organization.")
            name = membership.enterprise.name
            if not membership.is_active:
                raise Refused(f"Your membership of {name} has been deactivated.")
            owner = {"membership_id": membership.pk}
            no_licence = f"You need a licence to take the survey for {name}."
        draft = Response.objects.filter(
            account=account, membership=membership, status=Response.Status.DRAFT
        ).first()
        if draft is not None:
            return draft
        # Lock this context's active licences without joining other tables (a
        # join would make the lock unreliable), then ask which one is unused in a
        # fresh statement, which sees everything committed while we waited.
        list(Entitlement.objects.select_for_update().filter(revoked_at__isnull=True, **owner))
        licence = licences.unused_licence(account, membership)
        if licence is None:
            raise NoLicence(no_licence)
        version = current_version()
        if version is None:
            raise Refused("No survey is published yet.")
        # The context comes from the licence, never from the caller, so a
        # response and its licence cannot disagree about who may see it.
        response = Response.objects.create(
            account=account,
            survey_version=version,
            entitlement=licence,
            membership_id=licence.membership_id,
        )
        funnel.record_event(funnel.Kind.SURVEY_STARTED, tier=licence.tier, source=licence.source)
        return response


def save_self_report(response, took_before, via="", match_hint=""):
    """
    Record "Have you taken this survey before?" (True or False) and, if yes, how
    (one of Response.TookBeforeVia). Allowed on a draft until page 1 is locked.

    With a yes the person may also give `match_hint`: an email address or phone
    number they used then. It is optional and nothing depends on it. It is kept
    only until the background worker has used it, once, to look for their
    other account (queued here), and is then emptied.
    """
    if not isinstance(took_before, bool):
        raise Invalid("Please answer yes or no.")
    match_hint = " ".join(str(match_hint or "").split())
    if took_before:
        if via not in Response.TookBeforeVia.values:
            raise Invalid(
                "Please say how you took it: as an individual, through a company, or other."
            )
        if len(match_hint) > MATCH_HINT_MAX_LENGTH or "\x00" in match_hint:
            raise Invalid("That is too long for an email address or a phone number.")
    else:
        via = match_hint = ""
    with transaction.atomic():
        response = _lock(response)
        if response.pages_completed:
            raise Locked("This answer cannot be changed once page 1 is locked.")
        response.took_before = took_before
        response.took_before_via = via
        response.match_hint = match_hint
        response.save(update_fields=["took_before", "took_before_via", "match_hint"])
        if match_hint:
            accounts.look_for_duplicates_later(response.account)
        return response


def save_answer(response, question_id, value):
    """
    Store one answer: the question must belong to the response's survey version
    and sit on the page being answered (the first unlocked one, so nobody answers
    a statement they have not been shown); the value must be a whole number in the
    question's range.
    """
    with transaction.atomic():
        response = _lock(response)
        _apply_answer(response, question_id, value)
        response.save(update_fields=["answers"])
        return response


def complete_page(response, page, answers=None):
    """
    Lock a page (the Next button). It must be the next unlocked page and every
    statement on it must be answered; page 1 also needs the self-report.

    `answers` ({question id: value}) is what the page showed when Next was
    pressed. It is saved first, in the same transaction, so the page that gets
    locked is the page the person saw, even if an autosave failed or another tab
    saved something different. A page that is not complete yet keeps the valid
    choices it was sent; any other refusal leaves everything as it was.
    """
    with transaction.atomic():
        response = _lock(response)
        page = _whole_number(page)
        total = page_count(response)
        if page is None or not 1 <= page <= total:
            raise Invalid("There is no such page.")
        if page <= response.pages_completed:
            raise Locked("This page is already locked.")
        if page != response.pages_completed + 1:
            raise Invalid("Please finish the earlier pages first.")
        for question_id, value in (answers or {}).items():
            _apply_answer(response, question_id, value)
        on_page = [q for q in _questions(response) if page_of(q.position) == page]
        if page == 1 and response.took_before is None:
            refusal = Incomplete("Please say whether you have taken this survey before.")
        elif _unanswered(response, on_page):
            refusal = Incomplete(f"Please answer all {len(on_page)} statements on this page first.")
        else:
            response.pages_completed = page
            response.save(update_fields=["answers", "pages_completed"])
            funnel.record_event(
                funnel.Kind.PAGE_LOCKED,
                page=page,
                tier=response.entitlement.tier,
                source=response.entitlement.source,
            )
            return response
        # Not ready to lock, but keep the choices that were sent, so nobody has to
        # tick them again (raising inside the transaction would undo them).
        response.save(update_fields=["answers"])
    raise refusal


def submit(response):
    """Finish for good: every page locked and every statement answered."""
    with transaction.atomic():
        response = _lock(response)
        if response.pages_completed < page_count(response):
            raise Incomplete("Please finish every page first.")
        if response.took_before is None:
            raise Incomplete("Please say whether you have taken this survey before.")
        missing = _unanswered(response, _questions(response))
        if missing:
            raise Incomplete(f"{len(missing)} statement(s) still need an answer.")
        response.status = Response.Status.SUBMITTED
        response.submitted_at = timezone.now()
        response.possible_repeat = _is_possible_repeat(response)
        response.save(update_fields=["status", "submitted_at", "possible_repeat"])
        funnel.record_event(
            funnel.Kind.SURVEY_SUBMITTED,
            tier=response.entitlement.tier,
            source=response.entitlement.source,
        )
        # Someone who has now taken the survey is worth checking against the
        # other accounts, in the background (it changes nothing for them).
        accounts.look_for_duplicates_later(response.account)
        # And its result is worked out in the background too, so a slow or
        # failing algorithm can never hold up or undo a submission.
        jobs.enqueue(results.COMPUTE_RESULT, {"response_id": response.pk})
        return response


# --- possible repeats -------------------------------------------------------------


def _is_possible_repeat(response):
    """
    True if this looks like a second go at the survey: the person said they
    had taken it before, or an earlier submitted survey exists from this login
    or one linked to it (the same person). Two accounts that merely look
    alike, and that no superuser has linked, do not count.
    """
    return bool(response.took_before) or _earlier_by_same_person(response).exists()


def _earlier_by_same_person(response):
    account = response.account
    same_person = (
        Q(account__person_id=account.person_id) if account.person_id else Q(account=account)
    )
    earlier = Q(submitted_at__lt=response.submitted_at) | Q(
        submitted_at=response.submitted_at, pk__lt=response.pk
    )
    return Response.objects.filter(same_person, earlier, status=Response.Status.SUBMITTED)


def mark_possible_repeats(account_ids):
    """
    Work out "possible repeat" again for every submitted survey of these
    accounts. Called when two logins have just been linked, or a link undone:
    who counts as "the same person" has changed, so an earlier survey by the
    other login now counts, or no longer does. Returns how many marks changed.
    """
    changed = 0
    submitted = Response.objects.select_related("account").filter(
        account_id__in=account_ids, status=Response.Status.SUBMITTED
    )
    for response in submitted:
        now = _is_possible_repeat(response)
        if now != response.possible_repeat:
            Response.objects.filter(pk=response.pk).update(possible_repeat=now)
            changed += 1
    return changed


# --- helpers -------------------------------------------------------------------


def _lock(response):
    """Re-read the row under lock and refuse a submitted one. Raises DoesNotExist if gone."""
    locked = Response.objects.select_for_update().get(pk=response.pk)
    if locked.status != Response.Status.DRAFT:
        raise Locked("This survey has been submitted and cannot be changed.")
    return locked


def _apply_answer(response, question_id, value):
    """Check one answer and put it in response.answers; the caller holds the lock and saves."""
    question = _questions(response).filter(pk=_whole_number(question_id)).first()
    if question is None:
        raise Invalid("That statement is not part of this survey.")
    page = page_of(question.position)
    if response.pages_completed >= page:
        raise Locked("This page is locked; its answers can no longer be changed.")
    if page != response.pages_completed + 1:
        raise Invalid("Please finish the earlier pages first.")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not question.min_value <= value <= question.max_value
    ):
        raise Invalid(f"Choose a number from {question.min_value} to {question.max_value}.")
    response.answers[str(question.pk)] = value


def _questions(response):
    return Question.objects.filter(survey_version_id=response.survey_version_id)


def _unanswered(response, questions):
    return [q for q in questions if str(q.pk) not in response.answers]


def _whole_number(value):
    """An int from an int or a string of digits; None for anything else, bools included."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None
