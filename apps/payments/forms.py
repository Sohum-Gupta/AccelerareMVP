"""
What is typed on the buy pages: a tier, and for an organization a number of
licences. The forms only check the shape; the rules are in services.py.
"""

from django import forms

from .services import MAX_STOCK_PER_PURCHASE, TIERS


def _choices(prices):
    """The tier drop-down's lines: "Tier 2 licence, $2.00 each"."""
    return [(tier, f"Tier {tier} licence, {prices[tier]} each") for tier in TIERS if tier in prices]


class TierForm(forms.Form):
    """A Buy or Upgrade button: it sends one thing, the tier."""

    tier = forms.TypedChoiceField(choices=[(tier, tier) for tier in TIERS], coerce=int)


class BuyStockForm(forms.Form):
    """An organization's "Buy licences" form: which tier, and how many."""

    tier = forms.TypedChoiceField(
        label="Which licence",
        coerce=int,
        error_messages={
            "required": "Choose a tier.",
            "invalid_choice": "Choose a tier from the list.",
        },
    )
    quantity = forms.IntegerField(
        label="How many",
        min_value=1,
        max_value=MAX_STOCK_PER_PURCHASE,
        initial=1,
        help_text="You pay for all of them together on the next page. They go into your "
        "stock, and you give them to members when you like.",
        error_messages={
            "required": "Enter how many licences to buy.",
            "invalid": "Enter a whole number.",
            "min_value": f"Buy from 1 to {MAX_STOCK_PER_PURCHASE:,} licences at a time.",
            "max_value": f"Buy from 1 to {MAX_STOCK_PER_PURCHASE:,} licences at a time.",
        },
    )

    def __init__(self, *args, prices, **kwargs):
        """`prices` is {tier: "$2.00"}, as the page shows them."""
        super().__init__(*args, **kwargs)
        self.fields["tier"].choices = _choices(prices)
