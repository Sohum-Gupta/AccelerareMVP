"""
What possible duplicates do when an account is erased.

A possible duplicate is about two people who might be one. When one of them is
erased there is nothing left to decide, and the row itself says "these two
accounts have something in common", so it goes. An account that is deleted
outright takes its rows with it anyway; this also covers the account that is
stripped and kept for its results.
"""

from django.dispatch import receiver

from apps.accounts.erasure import account_erasing

from . import services


@receiver(account_erasing, dispatch_uid="matching.forget_possible_duplicates")
def forget_possible_duplicates(sender, account, **kwargs):
    """An account is being erased. Says how many possible duplicates went with it."""
    return {"possible_duplicates_removed": services.forget(account)}
