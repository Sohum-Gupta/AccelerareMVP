"""The self-report form. The rules live in services.save_self_report; this form
turns radio buttons and a drop-down into the True/False and choice it expects,
and gives a field-level error when "how" is missing after a "yes"."""

from django import forms

from .models import Response


class SelfReportForm(forms.Form):
    took_before = forms.ChoiceField(
        label="Have you taken this survey before?",
        choices=[("yes", "Yes"), ("no", "No")],
        widget=forms.RadioSelect,
    )
    took_before_via = forms.ChoiceField(
        label="How did you take it?",
        choices=[("", "Choose one"), *Response.TookBeforeVia.choices],
        required=False,
    )

    def clean(self):
        data = super().clean()
        if data.get("took_before") == "yes" and not data.get("took_before_via"):
            self.add_error("took_before_via", "Please say how you took it.")
        return data

    @property
    def answer(self):
        """(took_before, via) as the service wants them; call after is_valid()."""
        took_before = self.cleaned_data["took_before"] == "yes"
        return took_before, self.cleaned_data["took_before_via"] if took_before else ""

    @classmethod
    def for_draft(cls, response):
        """Pre-filled from a draft that already has the self-report."""
        if response is None or response.took_before is None:
            return cls()
        return cls(
            initial={
                "took_before": "yes" if response.took_before else "no",
                "took_before_via": response.took_before_via,
            }
        )
