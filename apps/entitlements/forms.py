"""
The one thing typed on an organization's Licences page: a tier, chosen from a
drop-down. The form only checks that it is 1, 2 or 3 and turns it into a
number; whether that tier has a licence left is for services.py to decide.
"""

from django import forms

from .services import TIERS


class TierForm(forms.Form):
    tier = forms.TypedChoiceField(choices=[(tier, f"Tier {tier}") for tier in TIERS], coerce=int)
