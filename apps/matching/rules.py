"""
The rules that say two accounts look like the same person.

Each rule takes one account and returns the numbers of other accounts that
match it. A rule only ever looks: it changes nothing. services.run_for_account
runs them all and brings each pair to a superuser.

Adding a rule is writing one function and adding it to RULES with a name and
the plain words the superuser reads.
"""

import unicodedata

from django.core.exceptions import ValidationError

from apps.accounts.models import Account, ContactPoint
from apps.accounts.normalisers import normalise_email, normalise_phone, phone_country


def name_key(full_name):
    """
    A full name in the form names are compared in: lower case, accents removed,
    spaces tidied. "José  GARCÍA" and "jose garcia" give the same key. There is
    no "close enough": two names match only if their keys are equal.
    """
    plain = unicodedata.normalize("NFKD", str(full_name or ""))
    plain = "".join(letter for letter in plain if not unicodedata.combining(letter))
    return " ".join(plain.casefold().split())


def same_phone(account):
    """Accounts that list a phone number this account lists. Verified or not: no phone can be verified yet."""
    numbers = account.contact_points.filter(kind=ContactPoint.Kind.PHONE).values_list(
        "value_normalised", flat=True
    )
    return set(
        ContactPoint.objects.filter(
            kind=ContactPoint.Kind.PHONE, value_normalised__in=list(numbers)
        )
        .exclude(account=account)
        .values_list("account_id", flat=True)
    )


def same_name(account):
    """
    Accounts with the same full name, when this account and the other each
    belong to some organization (the same one or different ones, and whether
    or not they have since left it). Two strangers who share a name are common;
    two members who do are worth a look, because the usual cause is one person
    invited at two addresses.
    """
    key = name_key(account.full_name)
    if not key or not account.memberships.exists():
        return set()
    # Compared here, not in the database, which cannot remove accents without
    # an extension. Only members are read, and this runs in the background.
    members = (
        Account.objects.filter(memberships__isnull=False)
        .exclude(pk=account.pk)
        .exclude(full_name="")
        .values_list("pk", "full_name")
        .distinct()
    )
    return {pk for pk, full_name in members if name_key(full_name) == key}


def match_box(account):
    """
    Accounts that own an email address or phone number this person typed into
    the box under "Yes, I have taken this survey before". The box is on a
    response, reached here through the account (this app never imports the
    responses app). services.run_for_account empties the box once it has been
    used, whether or not it found anyone.
    """
    found = set()
    for typed in account.responses.exclude(match_hint="").values_list("match_hint", flat=True):
        found |= owners_of(typed, account)
    return found


def owners_of(typed, account):
    """The other accounts that an address or number typed by this account belongs to."""
    if "@" in typed:
        # An address counts only once its owner has proven it, like everywhere else.
        owners = ContactPoint.objects.filter(
            kind=ContactPoint.Kind.EMAIL,
            value_normalised=normalise_email(typed),
            verified_at__isnull=False,
        )
    else:
        number = _as_phone(typed, account)
        if number is None:
            return set()
        owners = ContactPoint.objects.filter(kind=ContactPoint.Kind.PHONE, value_normalised=number)
    return set(owners.exclude(account=account).values_list("account_id", flat=True))


def _as_phone(typed, account):
    """
    What was typed as a full international number, or None if it is not a
    phone number. Typed with a leading + it says its own country; without one
    it is read as a number from the country of the person's own phone.
    """
    own = account.contact_points.filter(kind=ContactPoint.Kind.PHONE).values_list(
        "value_normalised", flat=True
    )
    for country in [None, *{phone_country(number) for number in own}]:
        try:
            return normalise_phone(typed, country)
        except ValidationError:
            continue
    return None


# (name stored on the pair, what the superuser reads, the rule)
RULES = [
    ("same_phone", "They gave the same phone number.", same_phone),
    (
        "same_name",
        "They have the same full name, and each belongs to an organization.",
        same_name,
    ),
    (
        "match_box",
        (
            "Asked whether they had taken the survey before, one of them typed an email "
            "address or phone number that belongs to the other."
        ),
        match_box,
    ),
]

WORDS = {name: words for name, words, _ in RULES}
