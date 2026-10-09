"""
Our hooks into allauth.

allauth asks its adapter whenever a decision depends on the site. Overriding a
method here changes allauth's behaviour without copying its views.
"""

from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """
        Closed: allauth's own signup page would create an account without a
        phone and without going through services.register. Our signup page
        (PR 4) calls register directly, so this stays False for good.
        """
        return False
