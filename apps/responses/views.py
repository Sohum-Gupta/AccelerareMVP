"""Thin views: read the form, call a service, show the result."""

from django.contrib import messages
from django.shortcuts import redirect, render

from apps.accounts.decorators import verified_email_required
from apps.entitlements import services as licences

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
        return render(request, "responses/disclosure.html", {"state": "in_progress"})
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
            messages.success(request, "Saved.")
            # PR 6 sends this to the first statement page instead.
            return redirect("responses:start")
    context = {"state": "ready", "form": form, "resuming": draft is not None}
    return render(request, "responses/disclosure.html", context)
