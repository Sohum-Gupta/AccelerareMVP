"""
Forms for the organization pages. A form only checks that something sensible
was typed; the rules themselves live in services.py, which is the authority.
"""

from django import forms

from .services import (
    CODE_ALPHABET,
    CODE_LENGTH,
    DEFAULT_CODE_DAYS,
    MAX_CODE_USES,
    NAME_MAX_LENGTH,
    TIERS,
    normalise_code,
)

# The longest a join code may last, in days.
MAX_CODE_DAYS = 365


def tier_field(label, help_text):
    """
    The optional "licence to give on joining" drop-down of the invite and join
    code forms: "No licence" (the default) or a tier, which the form hands
    over as None or a number.
    """
    return forms.TypedChoiceField(
        label=label,
        required=False,
        coerce=int,
        empty_value=None,
        choices=_tier_choices(None),
        help_text=help_text,
        error_messages={"invalid_choice": "Choose a tier from the list, or no licence."},
    )


def _tier_choices(left):
    """
    The drop-down's lines. With `left` ({tier: how many the stock can still
    promise}) each tier says so: "Tier 2 licence (3 left)". Every tier stays in
    the list even with none left; the service refuses it and says why, which
    is clearer than a tier that has silently gone.
    """

    def label(tier):
        if left is None:
            return f"Tier {tier} licence"
        number = left.get(tier, 0)
        return (
            f"Tier {tier} licence ({number:,} left)"
            if number
            else f"Tier {tier} licence (none left)"
        )

    return [("", "No licence"), *((tier, label(tier)) for tier in TIERS)]


class _StockAwareForm(forms.Form):
    """A form with the tier drop-down, told how many of each tier are left."""

    def __init__(self, *args, left=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tier"].choices = _tier_choices(left)


class EnterpriseForm(forms.Form):
    """The "Create an organization" page: one box, the name."""

    name = forms.CharField(
        label="Organization name",
        max_length=NAME_MAX_LENGTH,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
        help_text="Shown to the people you bring in. Two organizations may share a name.",
        error_messages={
            "required": "Enter the organization's name.",
            "max_length": f"Enter a name of at most {NAME_MAX_LENGTH} characters.",
        },
    )


class JoinCodeForm(_StockAwareForm):
    """The "New join code" form: how many people it lets in, and for how long."""

    max_uses = forms.IntegerField(
        label="How many people may use it",
        min_value=1,
        max_value=MAX_CODE_USES,
        initial=10,
        error_messages={
            "required": "Enter how many people may use the code.",
            "invalid": "Enter a whole number.",
            "min_value": f"Choose a number from 1 to {MAX_CODE_USES:,}.",
            "max_value": f"Choose a number from 1 to {MAX_CODE_USES:,}.",
        },
    )
    days = forms.IntegerField(
        label="Days until it expires",
        min_value=1,
        max_value=MAX_CODE_DAYS,
        initial=DEFAULT_CODE_DAYS,
        error_messages={
            "required": "Enter how many days the code should last.",
            "invalid": "Enter a whole number.",
            "min_value": f"Choose a number of days from 1 to {MAX_CODE_DAYS}.",
            "max_value": f"Choose a number of days from 1 to {MAX_CODE_DAYS}.",
        },
    )
    tier = tier_field(
        "Licence for each person who joins",
        "One licence is set aside from your stock for each person the code allows, so you "
        "need that many left. Those nobody takes come back when the code is switched off "
        "or expires.",
    )


class InviteForm(_StockAwareForm):
    """The "Invite someone" form: one email address, and the licence that comes with it."""

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autocomplete": "off"}),
        help_text="They can accept only from an account that has verified this address.",
        error_messages={
            "required": "Enter an email address.",
            "invalid": "Enter a valid email address.",
        },
    )
    tier = tier_field(
        "Licence to give them when they join",
        "The licence is set aside from your stock when the invite is sent, and comes back "
        "if the invite is withdrawn or expires.",
    )


class JoinForm(forms.Form):
    """
    The "Join an organization" page: one box, the code. Only its shape is
    checked here (ten characters a code can contain), which says nothing about
    whether such a code exists; services.check_code decides that.
    """

    code = forms.CharField(
        label="Join code",
        max_length=40,
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "autocapitalize": "characters", "spellcheck": "false"}
        ),
        help_text="Ten letters and digits, like ABCDE-FGH23. Capitals and the hyphen do not matter.",
        error_messages={"required": "Enter the join code."},
    )

    def clean_code(self):
        code = normalise_code(self.cleaned_data["code"])
        if len(code) != CODE_LENGTH or set(code) - set(CODE_ALPHABET):
            raise forms.ValidationError(
                "A join code is ten letters and digits, like ABCDE-FGH23. Check it and try again."
            )
        return code
