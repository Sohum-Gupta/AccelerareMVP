"""
Our hooks into allauth.

allauth asks its adapter whenever a decision depends on the site. Overriding a
method here changes allauth's behaviour without copying its views.
"""

import logging
from smtplib import SMTPException

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core import context as allauth_context
from django.contrib import messages
from django.db import transaction
from django.urls import reverse

from . import arrival, services

logger = logging.getLogger(__name__)


def describe_mail_error(error: Exception) -> str:
    """
    What may be logged about a refused email: the kind of error and the mail
    server's numeric reply codes. Never the error's own text, because a refusal
    quotes the address it refused ("Email address is not verified: x@y"), and a
    person's email must not reach the logs or Sentry.
    """
    codes = set()
    if getattr(error, "smtp_code", None) is not None:
        codes.add(error.smtp_code)
    # SMTPRecipientsRefused carries {address: (code, reply)}; keep the codes only.
    for reply in getattr(error, "recipients", {}).values():
        codes.add(reply[0])
    summary = type(error).__name__
    if codes:
        summary += " " + ", ".join(str(code) for code in sorted(codes))
    return summary


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """
        Closed: allauth's own signup page would create an account without a
        phone and without going through services.register. Our signup page
        (PR 4) calls register directly, so this stays False for good.
        """
        return False

    def get_login_redirect_url(self, request):
        """
        Where a login lands when the login page was given no "next" address.
        Someone who was on their way to join an organization (arrival.py) goes
        back to that page, once. Everyone else goes to "My surveys", the page
        that says what they can do next (the founder's choice, 2026-11-13;
        it used to be the profile). The exception is an account that still
        has something to put right before it can do anything: no verified
        email, or no name. That one goes to the account page, where both are.
        """
        on_the_way = arrival.take_next(request)
        if on_the_way:
            return on_the_way
        account = request.user
        if account.is_authenticated and (
            not account.full_name or not services.has_verified_email(account)
        ):
            return reverse("account_profile")
        return super().get_login_redirect_url(request)

    def confirm_email(self, request, email_address):
        """
        One transaction around allauth's write and our signal receiver, so
        the two email tables can never disagree about a verification.
        """
        with transaction.atomic():
            return super().confirm_email(request, email_address)

    def send_mail(self, template_prefix, email, context):
        """
        Every email allauth sends (verification links, password reset) comes
        through here. If the mail server refuses (Amazon SES refuses unverified
        addresses while it is in its sandbox), the person's account and
        addresses are already saved, so showing a 500 page would only lose them.
        Log it, tell them, and mark the request so our own views can adjust
        what they say.
        """
        try:
            super().send_mail(template_prefix, email, context)
        except (SMTPException, OSError) as error:
            logger.error("Could not send an email (%s)", describe_mail_error(error))
            request = allauth_context.request
            if request is not None:
                request.mail_failed = True
                messages.warning(
                    request,
                    "We could not send the email just now. Your details are saved; "
                    "please try again in a few minutes.",
                )
