"""
Tells Sentry which account met an error, by number (Milestone 7).

When something fails, the first question is "who was it, and can I reproduce
it?". Sentry is deliberately given no personal data (config/settings/
production.py: no request bodies, no local variables, send_default_pii off),
so an error report said nothing about who met it. This attaches the one thing
that is safe: the account's number. With it a superuser can open the account
in the Django admin; without access to the admin the number means nothing.

Never the email address, the name or anything else: only `id`.

On a laptop and in tests Sentry is not set up (no SENTRY_DSN), and setting the
user is then a call that does nothing.
"""

import sentry_sdk


class SentryAccountMiddleware:
    """After AuthenticationMiddleware: it needs to know who is logged in."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Asking who is logged in costs nothing for a visitor with no session
        # (no database query: a test holds /health to that).
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            sentry_sdk.set_user({"id": user.pk})
        else:
            # Nobody is logged in: say so, rather than leave the last request's account.
            sentry_sdk.set_user(None)
        return self.get_response(request)
