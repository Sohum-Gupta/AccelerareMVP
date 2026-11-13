"""
What part of a result a licence's tier lets a person see.

A result is worked out in full, once, and stored whole. The tier decides what
is shown when the page is drawn. That is why an upgrade can show more at once,
with no survey taken again and nothing worked out again.

FIELD_TIERS says, for each field of a result, the lowest tier that may see it.
A field that is not listed is shown to every tier. It is empty until the
algorithm exists and the shape of its output is known.
"""

FIELD_TIERS = {}


def visible_fields(payload, tier):
    """The fields of a result that this tier (1, 2 or 3) may see."""
    return {field: value for field, value in payload.items() if FIELD_TIERS.get(field, 1) <= tier}
