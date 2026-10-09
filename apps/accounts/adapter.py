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

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """
        Closed: allauth's own signup page would create an account without a
        phone and without going through services.register. Our signup page
        (PR 4) calls register directly, so this stays False for good.
        """
        return False

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
        except (SMTPException, OSError):
            logger.exception("Could not send an email")
            request = allauth_context.request
            if request is not None:
                request.mail_failed = True
                messages.warning(
                    request,
                    "We could not send the email just now. Your details are saved; "
                    "please try again in a few minutes.",
                )
