"""
Our hooks into allauth.

allauth asks its adapter whenever a decision depends on the site. Overriding a
method here changes allauth's behaviour without copying its views.
"""

from allauth.account.adapter import DefaultAccountAdapter
from django.db import transaction


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
