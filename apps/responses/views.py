"""
Thin views: read the form, call a service, show the result.

The pages of one attempt (page, save_answer, next_page, review, submit) are
behind _own_draft_required: a submitted response goes to its result, then the
licence gate, then ownership: the id in the address must be your own unfinished
response on a licence that is still active, or it is a 404. The gate is asked
in the attempt's own context: a personal attempt needs personal access, and one
taken for an organization needs the membership to be active still. Only one
page is ever shown: any other page number redirects to the page the person is
on, so a locked page cannot be reopened, nor a later one peeked at. History and
results need only a verified email.

Context. There are two start pages: /survey/start/ for a personal attempt and
/survey/start/<slug>/ for one taken for an organization. The second goes
through scoping.for_member, so the slug only says which organization is meant:
what comes back is this account's own active membership, or a 404. Everything
after the start page finds the context on the response itself. The templates
are given the organization's name and nothing else about it.
"""

from functools import wraps

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.accounts.decorators import verified_email_required
from apps.enterprises import scoping
from apps.enterprises.models import Membership
from apps.entitlements import services as licences
from apps.entitlements.models import Entitlement
from apps.survey.models import Question

from . import services
from .forms import SelfReportForm
from .models import Response


def _open_draft(account, membership=None):
    """The account's unfinished attempt in one context: personal unless a membership is given."""
    return Response.objects.filter(
        account=account, membership=membership, status=Response.Status.DRAFT
    ).first()


def _start_url(membership):
    """The start page of a context: personal, or the organization's."""
    if membership is None:
        return reverse("responses:start")
    return reverse("responses:start_for_organization", args=[membership.enterprise.slug])


def _organization(membership):
    """The organization's name for a template, or None for a personal attempt."""
    return membership.enterprise.name if membership is not None else None


@verified_email_required
def start(request):
    """The personal start page. See _start."""
    return _start(request, None)


@verified_email_required
def start_for_organization(request, slug):
    """
    The start page for taking the survey for an organization. Only an active
    member gets here; anyone else, and any slug that does not exist, is a 404.
    """
    return _start(request, scoping.for_member(request, slug))


def _start(request, membership):
    """
    The disclosure page: who sees the answers (and, for an organization, what
    its admins will see), how the survey works, and the self-report question.
    A GET writes nothing; the POST is what consumes a licence of this context
    (or resumes its draft) and saves the self-report.
    """
    here = _start_url(membership)
    context = {"organization": _organization(membership)}
    draft = _open_draft(request.user, membership)
    if not licences.has_survey_access(request.user, membership):
        return render(request, "responses/disclosure.html", {**context, "state": "no_licence"})
    if draft is not None and draft.pages_completed:
        # The self-report locked with page 1; nothing to ask here any more.
        if request.method == "POST":
            messages.info(request, "Your answer to that question is already locked in.")
            return redirect(here)
        context.update(state="in_progress", draft=draft)
        return render(request, "responses/disclosure.html", context)
    form = (
        SelfReportForm(request.POST)
        if request.method == "POST"
        else SelfReportForm.for_draft(draft)
    )
    if request.method == "POST" and form.is_valid():
        took_before, via, match_hint = form.answer
        try:
            response = services.start_response(request.user, membership)
            services.save_self_report(response, took_before, via, match_hint)
        except services.Refused as error:
            form.add_error(None, str(error))
        else:
            return redirect("responses:resume", response.pk)
    context.update(state="ready", form=form, resuming=draft is not None)
    return render(request, "responses/disclosure.html", context)


# --- the statement pages -------------------------------------------------------


def _own_draft_required(view):
    """
    For the pages of one attempt (/survey/<id>/...). A response already submitted
    goes to its result. Otherwise the licence gate (login, verified email,
    licence), then ownership: the id must be your own unfinished response on a
    licence that is still active, or it is a 404 (revoking deletes the draft; this
    is the second lock). The view gets the response instead of the id.

    The licence gate is asked in the attempt's own context. With no draft of
    yours under that id, or a personal one, it is the personal gate: without
    access you go to the start page, which explains that a licence is needed.
    For an organization's attempt the membership must still be active
    (deactivating deletes the draft; this is the second lock there too), and
    without access it is a 404.
    """

    @wraps(view)
    @verified_email_required
    def wrapper(request, pk, *args, **kwargs):
        mine = Response.objects.filter(pk=pk, account=request.user)
        if mine.filter(status=Response.Status.SUBMITTED).exists():
            return redirect("responses:result", pk)
        response = (
            mine.filter(status=Response.Status.DRAFT)
            .select_related("entitlement", "membership__enterprise")
            .first()
        )
        membership = response.membership if response is not None else None
        if not licences.has_survey_access(request.user, membership):
            if membership is not None:
                raise Http404
            # No message here: the start page says a licence is needed, in
            # its own box, and saying it twice was noise.
            return redirect("responses:start")
        if response is None or response.entitlement.revoked_at is not None:
            raise Http404
        return view(request, response, *args, **kwargs)

    return wrapper


def _where_now(response):
    """The address of the step this response is on."""
    if response.took_before is None:
        return _start_url(response.membership)
    if response.pages_completed >= services.page_count(response):
        return reverse("responses:review", args=[response.pk])
    return reverse("responses:page", args=[response.pk, response.pages_completed + 1])


def _gone(response):
    """
    Where to go when the draft vanished while a request was on its way (its
    licence was revoked, or the member was deactivated). A personal attempt
    goes to the start page, which explains about licences; an organization's
    goes to "My surveys", because its start page may no longer be theirs to see.
    """
    return redirect("responses:start" if response.membership_id is None else "responses:history")


def _number(raw):
    """A whole number typed into a form, or the raw text (which the services refuse)."""
    if isinstance(raw, str) and raw.isascii() and raw.isdigit():
        return int(raw)
    return raw


def _on_current_page(response, question_id):
    """The question if it is on the page being answered, else None (never another page's text)."""
    if not isinstance(question_id, int):
        return None
    question = Question.objects.filter(
        survey_version_id=response.survey_version_id, pk=question_id
    ).first()
    if question is None or services.page_of(question.position) != response.pages_completed + 1:
        return None
    return question


def _htmx_redirects(view):
    """
    A background (HTMX) request follows a redirect by itself and would put the
    page it lands on (the login page, say) inside a statement's box. Instead, tell
    HTMX to load that page in the whole window.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        if request.headers.get("HX-Request") and response.status_code in (301, 302, 303, 307, 308):
            whole_page = HttpResponse()
            whole_page["HX-Redirect"] = response["Location"]
            return whole_page
        return response

    return wrapper


@never_cache
@_own_draft_required
def resume(request, response):
    """Where to carry on: the first unlocked page, the review once all are locked."""
    return redirect(_where_now(response))


@never_cache
@_own_draft_required
def page(request, response, number):
    """The five statements of the page being answered, with the saved choices ticked."""
    here = reverse("responses:page", args=[response.pk, number])
    if _where_now(response) != here:
        return redirect(_where_now(response))
    questions = Question.objects.filter(survey_version_id=response.survey_version_id)
    statements = [
        {"question": question, "saved": response.answers.get(str(question.pk))}
        for question in questions.order_by("position")
        if services.page_of(question.position) == number
    ]
    context = {
        "response": response,
        "number": number,
        "page_count": services.page_count(response),
        "is_last": number >= services.page_count(response),
        "statements": statements,
        "organization": _organization(response.membership),
    }
    return render(request, "responses/page.html", context)


@never_cache
@_htmx_redirects
@_own_draft_required
def save_answer(request, response):
    """
    Autosave one click (HTMX). Answers with the statement as saved; a refusal is a
    409 with the reason. A page locked meanwhile (another tab) reloads the window
    on the page the person is really on.
    """
    if request.method != "POST":
        # e.g. back here after logging in again: carry on instead of an error page.
        return redirect("responses:resume", response.pk)
    question_id = _number(request.POST.get("question"))
    value = _number(request.POST.get(f"answer-{question_id}"))
    try:
        saved = services.save_answer(response, question_id, value)
    except services.Locked:
        messages.info(request, "That page was already locked, so here is where you are now.")
        return redirect("responses:resume", response.pk)
    except services.Refused as error:
        question = _on_current_page(response, question_id)
        if question is None:
            return HttpResponse(str(error), status=409, content_type="text/plain")
        context = {
            "response": response,
            "question": question,
            "saved": response.answers.get(str(question.pk)),
            "error": str(error),
        }
        return render(request, "responses/_statement.html", context, status=409)
    except Response.DoesNotExist:
        return _gone(response)
    question = _on_current_page(saved, question_id)
    context = {
        "response": saved,
        "question": question,
        "saved": saved.answers[str(question.pk)],
        "just_saved": True,
    }
    return render(request, "responses/_statement.html", context)


@never_cache
@_own_draft_required
def next_page(request, response):
    """
    The button under a page of statements: save the choices the page showed
    and lock it, then carry on. On every page but the last it reads "Next". On
    the last it reads "Submit", and locking that page also submits the survey:
    nothing is left to answer and no page can be reopened, so a separate
    "ready to submit" page would only be one more click.

    A page that is already locked is a double click, so carry on quietly.
    """
    if request.method != "POST":
        return redirect("responses:resume", response.pk)
    shown = {
        key.removeprefix("answer-"): _number(value)
        for key, value in request.POST.items()
        if key.startswith("answer-")
    }
    try:
        response = services.complete_page(response, request.POST.get("page"), shown)
    except services.Locked:
        pass
    except services.Refused as error:
        messages.error(request, str(error))
    except Response.DoesNotExist:
        return _gone(response)
    else:
        if response.pages_completed >= services.page_count(response):
            return _finish(request, response)
    return redirect("responses:resume", response.pk)


@never_cache
@_own_draft_required
def review(request, response):
    """
    Every page is locked and the survey is not submitted yet: how many are
    answered (never which or what), and Submit. The last page's own button
    submits, so a person only lands here if that could not finish (they lost
    the connection at that moment, say) and they have come back.
    """
    here = reverse("responses:review", args=[response.pk])
    if _where_now(response) != here:
        return redirect(_where_now(response))
    context = {
        "response_id": response.pk,
        "answered": len(services.answered_positions(response)),
        "total": Question.objects.filter(survey_version_id=response.survey_version_id).count(),
        "organization": _organization(response.membership),
    }
    return render(request, "responses/review.html", context)


@never_cache
@_own_draft_required
def submit(request, response):
    """
    Finish for good, then show the result. A second click finds it submitted and
    lands on the result too (the decorator sends it there, or the service says
    Locked if both clicks arrive together).
    """
    if request.method != "POST":
        return redirect("responses:review", response.pk)
    return _finish(request, response)


def _finish(request, response):
    """Submit a response whose pages are all locked, and go to its result."""
    try:
        services.submit(response)
    except services.Locked:
        pass
    except services.Refused as error:
        messages.error(request, str(error))
        return redirect("responses:resume", response.pk)
    except Response.DoesNotExist:
        return _gone(response)
    else:
        messages.success(request, "Submitted.")
    return redirect("responses:result", response.pk)


# --- history and results -------------------------------------------------------
# These need only a verified email, not a licence: past results stay visible,
# and so does a survey taken for an organization the person has since left.
# The templates get a summary (dates, status, tier, context), never the response
# itself, so no later template edit can print the answers by accident.

_WITH_CONTEXT = ("entitlement", "membership__enterprise")


def _summary(response):
    """What a person may see about one of their responses. Tier 0 means Free."""
    withdrawn = response.entitlement.revoked_at is not None
    return {
        "id": response.pk,
        "submitted": response.status == Response.Status.SUBMITTED,
        "started_at": response.started_at,
        "submitted_at": response.submitted_at,
        "tier": 0 if withdrawn else response.entitlement.tier,
        "withdrawn": withdrawn,
        # None for a personal attempt, else the organization it was taken for.
        "organization": _organization(response.membership),
    }


def _next_step(account, membership=None):
    """
    What the person can do next in one context: carry on with its draft, start
    on an unused licence, or neither. `organization` is None for personal.
    """
    if membership is None:
        active = Entitlement.objects.filter(
            person_id=account.person_id, membership__isnull=True, revoked_at__isnull=True
        )
    else:
        active = Entitlement.objects.filter(membership=membership, revoked_at__isnull=True)
    draft = _open_draft(account, membership)
    return {
        "organization": _organization(membership),
        "draft_id": draft.pk if draft is not None else None,
        "unused": active.filter(response__isnull=True).count(),
        # Tier 0: no licence that still counts in this context.
        "free": not active.exists(),
        "start_url": _start_url(membership),
    }


@never_cache
@verified_email_required
def history(request):
    """
    Every attempt of this account, newest first, each with its context, and
    what can be done next in each context: personal first, then every
    organization the account is an active member of.
    """
    account = request.user
    memberships = (
        Membership.objects.filter(account=account, status=Membership.Status.ACTIVE)
        .select_related("enterprise")
        .order_by("enterprise__name", "id")
    )
    context = {
        "rows": [_summary(r) for r in account.responses.select_related(*_WITH_CONTEXT)],
        "personal": _next_step(account),
        "organizations": [_next_step(account, membership) for membership in memberships],
    }
    return render(request, "responses/history.html", context)


@never_cache
@verified_email_required
def result(request, pk):
    """One submitted response: date, tier, context and (from Milestone 5) results. Never the answers."""
    response = get_object_or_404(
        Response.objects.select_related(*_WITH_CONTEXT), pk=pk, account=request.user
    )
    if response.status != Response.Status.SUBMITTED:
        return redirect("responses:resume", response.pk)
    return render(request, "responses/result.html", {"row": _summary(response)})
