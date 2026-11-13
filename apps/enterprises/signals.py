"""
What organizations do when an account is erased.

An invite holds the email address it was sent to. Erasing a person must remove
that address too, whether the invite was accepted, is still waiting, was
withdrawn or has expired, and whichever way the account itself is erased
(deleted or stripped). The invite row stays: it still counts towards the
organization's people limit, and an invite with no address can no longer be
accepted.

The memberships themselves are handled by accounts/erasure.py, which reaches
them through `account.memberships`.
"""

from django.db.models import Q
from django.dispatch import receiver

from apps.accounts.erasure import account_erasing

from .models import Invite


@receiver(account_erasing, dispatch_uid="enterprises.forget_invited_addresses")
def forget_invited_addresses(sender, account, emails, **kwargs):
    # Invites sent to an address the account has proven is theirs, and any
    # invite it joined with (the address may since have left the profile).
    theirs = Q(email__in=emails) | Q(memberships__account=account)
    # Says how many invites lost the address (one that is already empty is not counted).
    ids = list(Invite.objects.filter(theirs).exclude(email="").values_list("pk", flat=True))
    return {"invite_addresses_removed": Invite.objects.filter(pk__in=ids).update(email="")}
