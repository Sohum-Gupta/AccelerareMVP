"""Forms for pages we own. Validation of the values themselves lives in services.py."""

import pycountry
from allauth.account.forms import ResetPasswordForm
from django import forms

from . import services

# Shown first, in this order, then everyone else alphabetically.
FIRST_COUNTRIES = ["US", "IN", "GB"]


def country_choices() -> list[tuple[str, str]]:
    """(ISO code, name) pairs. The code is what normalise_phone expects ("GB", not "UK")."""
    names = {c.alpha_2: c.name for c in pycountry.countries}
    first = [(code, names[code]) for code in FIRST_COUNTRIES]
    rest = sorted(
        ((code, name) for code, name in names.items() if code not in FIRST_COUNTRIES),
        key=lambda pair: pair[1],
    )
    return [*first, *rest]


class SignupForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(
        label="Phone",
        widget=forms.TextInput(
            attrs={"type": "tel", "autocomplete": "tel-national", "data-phone-input": ""}
        ),
        help_text="Used to tell people apart. We do not text you yet.",
    )
    country = forms.ChoiceField(
        label="Country of your phone number",
        choices=country_choices,
        help_text="So we can read a number typed without the country code.",
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Password again",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("password1")
            and cleaned.get("password2")
            and cleaned["password1"] != cleaned["password2"]
        ):
            self.add_error("password2", "The two passwords do not match.")
        return cleaned


class PasswordResetRequestForm(ResetPasswordForm):
    """
    allauth's reset form with two changes. It looks the address up only among
    verified contact points (allauth would also fall back to unverified rows and
    to Account.email), and it never says whether an account exists: an unknown
    address passes validation and simply gets no mail.
    """

    def clean_email(self):
        typed = self.cleaned_data["email"].strip()
        self.account = services.account_for_reset(typed)
        self.users = [self.account] if self.account else []
        return typed

    def save(self, request, **kwargs):
        email = super().save(request, **kwargs)
        if self.account:
            services.send_reset_notice(request, self.account, email)
        return email
