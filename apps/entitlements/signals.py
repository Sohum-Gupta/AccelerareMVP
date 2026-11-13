"""
What the licences app does when someone joins an organization.

An invite or a join code can carry a tier. The organizations app cannot give a
licence itself (it may not import this app), so it announces every join with
its `member_joined` signal, and the receiver below gives the new member the
licence of that tier that was set aside when the invite or code was made.

The join and the licence happen together or not at all: an error here is not
caught, so it undoes the whole join (enterprises.services._announce_join).
"""

from django.dispatch import receiver

from apps.enterprises.services import member_joined

from . import services


@receiver(member_joined, dispatch_uid="entitlements.licence_on_joining")
def licence_on_joining(sender, membership, tier, **kwargs):
    if tier is not None:
        services.give_seat_on_joining(membership, tier)
