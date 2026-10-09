"""Thin views: read the form, call a service, show the result."""

from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from . import services
from .forms import SignupForm


def signup(request):
    if request.user.is_authenticated:
        return redirect("/")
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
