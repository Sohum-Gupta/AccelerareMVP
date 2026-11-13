"""
The background job the matching app knows how to do (see apps/jobs).

Other apps queue it by name, with the account's number, whenever something
that could make two accounts look alike has just changed
(accounts.services.look_for_duplicates_later). Running it twice is harmless:
a pair is stored once.
"""

from apps.accounts.services import LOOK_FOR_DUPLICATES
from apps.jobs import services as jobs

from . import services


@jobs.job(LOOK_FOR_DUPLICATES)
def look_for_duplicates(account_id):
    services.run_for_account(account_id)
