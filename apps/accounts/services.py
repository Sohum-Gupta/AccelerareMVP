"""
Account writes and the normalisers they depend on.

Views stay thin; anything that creates or changes accounts, people or contact
points goes through this module so the rules live in one place.
"""


def normalise_email(value: str) -> str:
    """
    Lowercase and trim, nothing else. Gmail dots and plus-aliases are kept on
    purpose: matching must be exact, so `b.ob@gmail.com` and `bob@gmail.com`
    are two different addresses to us.
    """
    return value.strip().lower()
