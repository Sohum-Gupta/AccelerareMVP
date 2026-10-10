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
erasure), then the person row (so two logins sharing one person cannot both
consume the same licence), then the person's licences (so a revoke cannot slip
in between choosing a licence and using it). The database constraints (one
licence one attempt, one open draft per account) are the backstop.

A write the rules do not allow raises Refused or one of its subclasses with a
plain-words message; the views turn it into a 409. A funnel event is recorded
inside the same transaction as the thing it counts, so a refusal or a rollback
leaves no event.
"""

import math

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Account, Person
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.funnel import services as funnel
from apps.survey.models import Question
from apps.survey.services import PAGE_SIZE, current_version

from .models import Response


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


def start_response(account):
    """
    The account's open draft, or a new one on its oldest unused licence.
    Raises NoLicence when there is neither.
    """
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        if not account.is_active or account.anonymised_at is not None or account.person_id is None:
            raise Refused("This account cannot take the survey.")
        Person.objects.select_for_update().get(pk=account.person_id)
        draft = Response.objects.filter(account=account, status=Response.Status.DRAFT).first()
        if draft is not None:
            return draft
        # Lock the person's active licences without joining other tables (a join
        # would make the lock unreliable), then ask which one is unused in a fresh
        # statement, which sees everything committed while we waited.
        list(
            Entitlement.objects.select_for_update().filter(
                person_id=account.person_id, revoked_at__isnull=True
            )
        )
        licence = licences.unused_licence(account)
        if licence is None:
            raise NoLicence("You need a licence to take the survey.")
        version = current_version()
        if version is None:
            raise Refused("No survey is published yet.")
        response = Response.objects.create(
            account=account, survey_version=version, entitlement=licence
        )
        funnel.record_event(funnel.Kind.SURVEY_STARTED, tier=licence.tier, source=licence.source)
        return response


def save_self_report(response, took_before, via=""):
    """
    Record "Have you taken this survey before?" (True or False) and, if yes, how
    (one of Response.TookBeforeVia). Allowed on a draft until page 1 is locked.
    """
    if not isinstance(took_before, bool):
        raise Invalid("Please answer yes or no.")
    if took_before:
        if via not in Response.TookBeforeVia.values:
            raise Invalid(
                "Please say how you took it: as an individual, through a company, or other."
            )
    else:
        via = ""
    with transaction.atomic():
        response = _lock(response)
        if response.pages_completed:
            raise Locked("This answer cannot be changed once page 1 is locked.")
        response.took_before = took_before
        response.took_before_via = via
        response.save(update_fields=["took_before", "took_before_via"])
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
    saved something different. Any refusal leaves everything as it was.
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
        if page == 1 and response.took_before is None:
            raise Incomplete("Please say whether you have taken this survey before.")
        on_page = [q for q in _questions(response) if page_of(q.position) == page]
        if _unanswered(response, on_page):
            raise Incomplete(f"Please answer all {len(on_page)} statements on this page first.")
        response.pages_completed = page
        response.save(update_fields=["answers", "pages_completed"])
        funnel.record_event(
            funnel.Kind.PAGE_LOCKED,
            page=page,
            tier=response.entitlement.tier,
            source=response.entitlement.source,
        )
        return response


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
        response.save(update_fields=["status", "submitted_at"])
        funnel.record_event(
            funnel.Kind.SURVEY_SUBMITTED,
            tier=response.entitlement.tier,
            source=response.entitlement.source,
        )
        return response


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
