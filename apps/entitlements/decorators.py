"""
The personal licence gate, as a decorator.

`survey_access_required` applies `verified_email_required` itself (so login,
verified email and licence are checked in that order with one decorator) and
then asks services.has_survey_access for the personal context: an unused
personal licence, or an open personal draft on a licence that is still active.
Without access the person is sent to the start page, which explains that a
licence is needed.

The pages of one attempt no longer use it: since an attempt can be for an
organization, they ask the same question in the attempt's own context
(responses/views.py, `_own_draft_required`). This stays for a page that is
personal by nature.

This checks access, not ownership of a particular response: entitlements must
not import responses, so "is this draft yours" is checked in the responses views.
"""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from apps.accounts.decorators import verified_email_required

from . import services


def survey_access_required(view):
    @wraps(view)
    @verified_email_required
    def wrapper(request, *args, **kwargs):
        if not services.has_survey_access(request.user):
            messages.warning(request, "You need a licence to take the survey.")
            return redirect("responses:start")
        return view(request, *args, **kwargs)

    return wrapper
