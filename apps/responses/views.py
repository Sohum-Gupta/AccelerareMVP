"""
Thin views: read the form, call a service, show the result.

The statement pages (page, save_answer, next_page, review) are behind
survey_access_required, which checks login, verified email and licence. Which
response is yours is checked here, by _own_draft: the id in the address must be
your own unfinished response on a licence that is still active, or it is a 404.
Only one page is ever shown: any other page number redirects to the page the
person is on, so a locked page cannot be reopened, nor a later one peeked at.
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


def _own_draft(request, pk):
    """
    The person's own unfinished response with this id, or a 404. A draft on a
    revoked licence counts as gone (revoking deletes it; this is the second lock).
    """
    response = get_object_or_404(
        Response.objects.select_related("entitlement"),
        pk=pk,
        account=request.user,
        status=Response.Status.DRAFT,
    )
    if response.entitlement.revoked_at is not None:
        raise Http404
    return response


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
@survey_access_required
def resume(request, pk):
    """Where to carry on: the first unlocked page, the review once all are locked."""
    return redirect(_where_now(_own_draft(request, pk)))


@never_cache
@survey_access_required
def page(request, pk, number):
    """The five statements of the page being answered, with the saved choices ticked."""
    response = _own_draft(request, pk)
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
@survey_access_required
def save_answer(request, pk):
    """
    Autosave one click (HTMX). Answers with the statement as saved; a refusal is a
    409 with the reason. A page locked meanwhile (another tab) reloads the window
    on the page the person is really on.
    """
    if request.method != "POST":
        # e.g. back here after logging in again: carry on instead of an error page.
        return redirect("responses:resume", pk)
    response = _own_draft(request, pk)
    question_id = _number(request.POST.get("question"))
    value = _number(request.POST.get(f"answer-{question_id}"))
    try:
        response = services.save_answer(response, question_id, value)
    except services.Locked:
        messages.info(request, "That page was already locked, so here is where you are now.")
        return redirect("responses:resume", pk)
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
    question = _on_current_page(response, question_id)
    context = {
        "response": response,
        "question": question,
        "saved": response.answers[str(question.pk)],
        "just_saved": True,
    }
    return render(request, "responses/_statement.html", context)


@never_cache
@survey_access_required
def next_page(request, pk):
    """
    The Next button: save the choices the page showed and lock it, then carry on.
    A page that is already locked is a double click, so carry on quietly.
    """
    if request.method != "POST":
        return redirect("responses:resume", pk)
    response = _own_draft(request, pk)
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
    return redirect("responses:resume", pk)


@never_cache
@survey_access_required
def review(request, pk):
    """Placeholder until PR 7: every page is locked; submitting comes next."""
    response = _own_draft(request, pk)
    here = reverse("responses:review", args=[response.pk])
    if _where_now(response) != here:
        return redirect(_where_now(response))
    return render(request, "responses/review.html", {"page_count": services.page_count(response)})
