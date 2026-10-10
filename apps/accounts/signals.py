"""
What happens when allauth confirms an email: copy the proof into ContactPoint.

allauth has already refused the click if another account verified the same
address, so by the time this runs the ContactPoint update cannot break the
one-owner rule unless the two tables have drifted apart. The adapter wraps the
whole confirmation in one transaction, so if this ever fails nothing is left
half done.
"""

from allauth.account.signals import email_confirmed
from django.dispatch import receiver
from django.utils import timezone

from apps.funnel import services as funnel

from .models import ContactPoint


@receiver(email_confirmed)
def mark_contact_verified(sender, request, email_address, **kwargs):
    # Only an account's first verified email is a funnel step; a second address,
    # or the same link clicked twice, is not.
    first = not ContactPoint.objects.filter(
        account_id=email_address.user_id,
        kind=ContactPoint.Kind.EMAIL,
        verified_at__isnull=False,
    ).exists()
    changed = ContactPoint.objects.filter(
        account_id=email_address.user_id,
        kind=ContactPoint.Kind.EMAIL,
        value_normalised=email_address.email,
        verified_at__isnull=True,
    ).update(verified_at=timezone.now())
    if first and changed:
        funnel.record_event(funnel.Kind.EMAIL_VERIFIED)
