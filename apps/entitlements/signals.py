"""
What the licences app does when someone joins an organization.

An invite or a join code can carry a tier. The organizations app cannot give a
licence itself (it may not import this app), so it announces every join with
its `member_joined` signal, and the receiver below gives the new member a
licence of that tier out of the organization's stock, if one is left.

The join never depends on this: the sender runs its listeners inside a
savepoint and carries on if one fails (enterprises.services._announce_join).
"""

from django.dispatch import receiver

from apps.enterprises.services import member_joined

from . import services


@receiver(member_joined, dispatch_uid="entitlements.licence_on_joining")
def licence_on_joining(sender, membership, tier, **kwargs):
    if tier is not None:
        services.give_seat_on_joining(membership, tier)
