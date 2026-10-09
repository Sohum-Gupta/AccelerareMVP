"""
Guards for views.

`verified_email_required` is the second lock on a door. allauth's mandatory
verification already stops a normal sign-up from logging in before the link is
clicked; this catches accounts that never went through that flow (createsuperuser,
or one made in a shell). Milestone 2 puts it on every response view.

It is our own rather than allauth's of the same name, because allauth's sends a
new verification email on every hit and answers with a page (status 200). This
one sends nothing and redirects to the profile page, which is deliberately not
decorated: it is where an unverified person adds and verifies an email.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from . import services


def verified_email_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not services.has_verified_email(request.user):
            messages.warning(request, "Verify your email address to continue.")
            return redirect("account_profile")
        return view(request, *args, **kwargs)

    return wrapper
