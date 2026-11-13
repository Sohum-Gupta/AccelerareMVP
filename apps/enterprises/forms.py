"""
Forms for the organization pages. A form only checks that something sensible
was typed; the rules themselves live in services.py, which is the authority.
"""

from django import forms

from .services import NAME_MAX_LENGTH


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
