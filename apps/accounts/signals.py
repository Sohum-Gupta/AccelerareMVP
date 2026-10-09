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

from .models import ContactPoint


@receiver(email_confirmed)
def mark_contact_verified(sender, request, email_address, **kwargs):
    ContactPoint.objects.filter(
        account_id=email_address.user_id,
        kind=ContactPoint.Kind.EMAIL,
        value_normalised=email_address.email,
        verified_at__isnull=True,
    ).update(verified_at=timezone.now())
