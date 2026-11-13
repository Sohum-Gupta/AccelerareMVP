"""
Forms for the organization pages. A form only checks that something sensible
was typed; the rules themselves live in services.py, which is the authority.
"""

from django import forms

from .services import DEFAULT_CODE_DAYS, MAX_CODE_USES, NAME_MAX_LENGTH

# The longest a join code may last, in days.
MAX_CODE_DAYS = 365


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


class JoinCodeForm(forms.Form):
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


class InviteForm(forms.Form):
    """The "Invite someone" form: one email address."""

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autocomplete": "off"}),
        help_text="They can accept only from an account that has verified this address.",
        error_messages={
            "required": "Enter an email address.",
            "invalid": "Enter a valid email address.",
        },
    )
