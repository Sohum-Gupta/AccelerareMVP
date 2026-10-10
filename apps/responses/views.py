"""
Thin views: read the form, call a service, show the result.

The pages of one attempt (page, save_answer, next_page, review, submit) are
behind _own_draft_required: a submitted response goes to its result, then the
licence gate (survey_access_required), then ownership: the id in the address must
be your own unfinished response on a licence that is still active, or it is a
404. Only one page is ever shown: any other page number redirects to the page the
person is on, so a locked page cannot be reopened, nor a later one peeked at.
History and results need only a verified email.
"""

from functools import wraps

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.accounts.decorators import verified_email_required
from apps.entitlements import services as licences
from apps.entitlements.decorators import survey_access_required
from apps.entitlements.models import Entitlement
from apps.survey.models import Question

from . import services
from .forms import SelfReportForm
from .models import Response


def _open_draft(account):
    return Response.objects.filter(account=account, status=Response.Status.DRAFT).first()


@verified_email_required
def start(request):
    """
    The disclosure page: who sees the answers, how the survey works, and the
    self-report question. A GET writes nothing; the POST is what consumes the
    licence (or resumes the draft) and saves the self-report.
    """
    draft = _open_draft(request.user)
    if not licences.has_survey_access(request.user):
        return render(request, "responses/disclosure.html", {"state": "no_licence"})
    if draft is not None and draft.pages_completed:
        # The self-report locked with page 1; nothing to ask here any more.
        if request.method == "POST":
            messages.info(request, "Your answer to that question is already locked in.")
            return redirect("responses:start")
        context = {"state": "in_progress", "draft": draft}
        return render(request, "responses/disclosure.html", context)
    form = (
        SelfReportForm(request.POST)
        if request.method == "POST"
        else SelfReportForm.for_draft(draft)
    )
    if request.method == "POST" and form.is_valid():
        took_before, via = form.answer
        try:
            response = services.start_response(request.user)
            services.save_self_report(response, took_before, via)
        except services.Refused as error:
            form.add_error(None, str(error))
        else:
            return redirect("responses:resume", response.pk)
    context = {"state": "ready", "form": form, "resuming": draft is not None}
    return render(request, "responses/disclosure.html", context)


# --- the statement pages -------------------------------------------------------


def _own_draft_required(view):
    """
    For the pages of one attempt (/survey/<id>/...). A response already submitted
    goes to its result. Otherwise the licence gate (login, verified email,
    licence), then ownership: the id must be your own unfinished response on a
    licence that is still active, or it is a 404 (revoking deletes the draft; this
    is the second lock). The view gets the response instead of the id.
    """

    @wraps(view)
    def own(request, pk, *args, **kwargs):
        response = get_object_or_404(
            Response.objects.select_related("entitlement"),
            pk=pk,
            account=request.user,
            status=Response.Status.DRAFT,
        )
        if response.entitlement.revoked_at is not None:
            raise Http404
        return view(request, response, *args, **kwargs)

    gated = survey_access_required(own)

    @wraps(view)
    @verified_email_required
    def wrapper(request, pk, *args, **kwargs):
        submitted = Response.objects.filter(
            pk=pk, account=request.user, status=Response.Status.SUBMITTED
        )
        if submitted.exists():
            return redirect("responses:result", pk)
        return gated(request, pk, *args, **kwargs)

    return wrapper


def _where_now(response):
    """The address of the step this response is on."""
    if response.took_before is None:
        return reverse("responses:start")
    if response.pages_completed >= services.page_count(response):
        return reverse("responses:review", args=[response.pk])
    return reverse("responses:page", args=[response.pk, response.pages_completed + 1])


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
        "statements": statements,
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
        return redirect("responses:start")
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
    The Next button: save the choices the page showed and lock it, then carry on.
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
        services.complete_page(response, request.POST.get("page"), shown)
    except services.Locked:
        pass
    except services.Refused as error:
        messages.error(request, str(error))
    except Response.DoesNotExist:
        return redirect("responses:start")
    return redirect("responses:resume", response.pk)


@never_cache
@_own_draft_required
def review(request, response):
    """Every page is locked: how many are answered (never which or what), and Submit."""
    here = reverse("responses:review", args=[response.pk])
    if _where_now(response) != here:
        return redirect(_where_now(response))
    context = {
        "response_id": response.pk,
        "answered": len(services.answered_positions(response)),
        "total": Question.objects.filter(survey_version_id=response.survey_version_id).count(),
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
    try:
        services.submit(response)
    except services.Locked:
        pass
    except services.Refused as error:
        messages.error(request, str(error))
        return redirect("responses:resume", response.pk)
    except Response.DoesNotExist:
        return redirect("responses:start")
    else:
        messages.success(request, "Submitted.")
    return redirect("responses:result", response.pk)


# --- history and results -------------------------------------------------------
# These need only a verified email, not a licence: past results stay visible.
# The templates get a summary (dates, status, tier), never the response itself,
# so no later template edit can print the answers by accident.


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
    }


@never_cache
@verified_email_required
def history(request):
    """Every attempt of this account, newest first, with Start or Continue."""
    responses = request.user.responses.select_related("entitlement")
    draft = _open_draft(request.user)
    active = Entitlement.objects.filter(person_id=request.user.person_id, revoked_at__isnull=True)
    context = {
        "rows": [_summary(response) for response in responses],
        "draft_id": draft.pk if draft is not None else None,
        "unused": active.filter(response__isnull=True).count(),
        # Tier 0: no licence that still counts, so the account is on the free tier.
        "free": not active.exists(),
    }
    return render(request, "responses/history.html", context)


@never_cache
@verified_email_required
def result(request, pk):
    """One submitted response: date, tier and (from Milestone 5) results. Never the answers."""
    response = get_object_or_404(
        Response.objects.select_related("entitlement"), pk=pk, account=request.user
    )
    if response.status != Response.Status.SUBMITTED:
        return redirect("responses:resume", response.pk)
    return render(request, "responses/result.html", {"row": _summary(response)})
