"""
Pure functions that turn what a person typed into the one form we compare.

No database and no models here, so both models.py and services.py can import
them without importing each other.
"""

import phonenumbers
from django.core.exceptions import ValidationError


def normalise_email(value: str) -> str:
    """
    Lowercase and trim, nothing else. Gmail dots and plus-aliases are kept on
    purpose: matching must be exact, so `b.ob@gmail.com` and `bob@gmail.com`
    are two different addresses to us.
    """
    return value.strip().lower()


FULL_NAME_MAX_LENGTH = 150  # the same number as Account.full_name


def clean_full_name(value: str) -> str:
    """
    A person's name as we store it: trimmed, with runs of spaces collapsed to
    one. Nothing else is changed (no capitalising, no splitting into first and
    last), because names differ too much to guess at. Raises ValidationError
    for an empty or over-long name.
    """
    name = " ".join((value or "").split())
    if not name:
        raise ValidationError("Enter your name.", code="required")
    if "\x00" in name:
        # PostgreSQL refuses a NUL character in text.
        raise ValidationError("Enter your name.", code="invalid")
    if len(name) > FULL_NAME_MAX_LENGTH:
        raise ValidationError(
            f"Enter a name of at most {FULL_NAME_MAX_LENGTH} characters.", code="max_length"
        )
    return name


def normalise_phone(value: str, country: str | None) -> str:
    """
    Return the number in international form (E.164, e.g. `+919876543210`) so
    the same number typed with spaces, a leading zero or a country code always
    compares equal.

    `country` is the two-letter code from the form's selector ("IN", "US",
    "GB"; note the UK's code is GB). A number typed with a leading `+` carries
    its own country and ignores the selector. Raises ValidationError for
    anything that is not a real number for that country.
    """
    try:
        number = phonenumbers.parse(value, country)
    except phonenumbers.NumberParseException:
        raise ValidationError("Enter a valid phone number.", code="invalid_phone") from None
    # is_valid_number checks the country's real number patterns, which is
    # stricter than is_possible_number (length only). "123" parses but fails.
    if not phonenumbers.is_valid_number(number):
        raise ValidationError("Enter a valid phone number.", code="invalid_phone")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def phone_country(e164: str) -> str:
    """Two-letter country of a normalised number ("IN", "US", "GB"), or "" if unknown."""
    try:
        return phonenumbers.region_code_for_number(phonenumbers.parse(e164)) or ""
    except phonenumbers.NumberParseException:
        return ""


def display_phone(e164: str) -> str:
    """
    The form a person reads: `+91 98765 43210`, `+1 415-555-2671`. Always
    carries the country code, so numbers from different countries do not look
    alike on the profile page. Takes the E.164 string normalise_phone returned.
    """
    number = phonenumbers.parse(e164, None)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
