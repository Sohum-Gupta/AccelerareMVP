"""Thin views: read the form, call a service, show the result."""

import logging
from smtplib import SMTPException

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import AddEmailForm, PhoneForm, SignupForm
from .models import ContactPoint

logger = logging.getLogger(__name__)


def signup(request):
    if request.user.is_authenticated:
        return redirect("account_profile")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.register(
                data["email"], data["phone"], data["country"], data["password1"], request
            )
        except services.EmailInUse:
            # Same page as success: this form must never reveal who has an account.
            pass
        except ValidationError as error:
            form.add_error(None, error)
        if not form.errors:
            # Redirect rather than render, so a refresh does not resubmit the form.
            return redirect("account_email_verification_sent")
    return render(request, "account/signup.html", {"form": form})


def _render_profile(request, add_email_form=None, phone_form=None):
    account = request.user
    contacts = list(account.contact_points.all())
    emails = [c for c in contacts if c.kind == ContactPoint.Kind.EMAIL]
    phone = next((c for c in contacts if c.kind == ContactPoint.Kind.PHONE), None)
    if phone_form is None:
        # E.164 is a safe thing to put back in the box: a leading + overrides the country.
        phone_form = PhoneForm(initial={"phone": phone.value_normalised} if phone else None)
    context = {
        "emails": emails,
        "phone": phone,
        "add_email_form": add_email_form or AddEmailForm(),
        "phone_form": phone_form,
        # A nudge only: the add-email form is on the page whether or not it shows.
        "show_personal_email_prompt": len(emails) == 1
        and account.personal_email_prompt_dismissed_at is None,
    }
    return render(request, "accounts/profile.html", context)


def _send_link(request, email):
    """Mail failures (SES is still in its sandbox) must not lose the address we just saved."""
    try:
        services.send_verification(request, request.user, email)
    except (SMTPException, OSError):
        logger.exception("Could not send a verification link")
        messages.warning(
            request, f"Added {email}, but we could not send the link. Try Resend in a minute."
        )
        return
    messages.success(request, f"Added {email}. We sent it a link; open it to verify the address.")


@login_required
def profile(request):
    return _render_profile(request)


@login_required
@require_POST
def add_email(request):
    form = AddEmailForm(request.POST)
    if form.is_valid():
        try:
            contact = services.add_email(request.user, form.cleaned_data["email"])
        except ValidationError as error:
            form.add_error("email", error)
        else:
            _send_link(request, contact.value_normalised)
            return redirect("account_profile")
    return _render_profile(request, add_email_form=form)


def _contact_action(request, pk, action, success):
    """Run one service on one of this account's contacts, then go back to the profile."""
    contact = get_object_or_404(ContactPoint, pk=pk, account=request.user)
    try:
        action(request.user, contact)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, success.format(contact.value_display))
    return redirect("account_profile")


@login_required
@require_POST
def resend_verification(request, pk):
    return _contact_action(
        request,
        pk,
        lambda account, contact: services.resend_verification(request, account, contact),
        "We sent a new link to {}.",
    )


@login_required
@require_POST
def make_primary(request, pk):
    return _contact_action(request, pk, services.make_primary, "{} is now your login address.")


@login_required
@require_POST
def remove_contact(request, pk):
    return _contact_action(request, pk, services.remove_contact, "Removed {}.")


@login_required
@require_POST
def change_phone(request):
    form = PhoneForm(request.POST)
    if form.is_valid():
        try:
            services.change_phone(
                request.user, form.cleaned_data["phone"], form.cleaned_data["country"]
            )
        except ValidationError as error:
            form.add_error("phone", error)
        else:
            messages.success(request, "Phone saved.")
            return redirect("account_profile")
    return _render_profile(request, phone_form=form)


@login_required
@require_POST
def dismiss_personal_email_prompt(request):
    services.dismiss_personal_email_prompt(request.user)
    return redirect("account_profile")
