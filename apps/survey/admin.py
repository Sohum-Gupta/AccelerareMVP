import json

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from . import services
from .models import Question, SurveyVersion

# Questions are changed through services.load_questions (the private file), so
# the admin only shows them. A superuser loads the file on the survey version's
# "Load the survey wording" page; nothing on that page or in its history entry
# ever repeats the wording.


class ReadOnlyQuestions(admin.TabularInline):
    model = Question
    extra = 0
    can_delete = False
    fields = ("position", "text", "min_value", "max_value", "metadata")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class WordingForm(forms.Form):
    """Step 1: the file, pasted or uploaded. Checking it writes nothing."""

    wording = forms.CharField(
        label="Paste the JSON",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 12, "cols": 80, "autocomplete": "off", "spellcheck": "false"}
        ),
    )
    file = forms.FileField(label="Or choose the file", required=False)

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.version = version

    def clean(self):
        cleaned = super().clean()
        pasted = cleaned.get("wording", "")
        upload = cleaned.get("file")
        if self.errors:
            return cleaned
        if pasted and upload:
            raise ValidationError("Paste the JSON or choose a file, not both.")
        if not pasted and not upload:
            raise ValidationError("Paste the JSON or choose a file.")
        # One byte over the limit is enough for parse_questions to refuse it.
        raw = upload.read(services.MAX_FILE_BYTES + 1) if upload else pasted
        self.entries = services.parse_questions(raw)
        self.changes, self.fingerprint = services.compare_questions(self.version, self.entries)
        return cleaned


class ApplyForm(forms.Form):
    """
    Step 2: the checked file comes back in a hidden field, so the wording stays
    in the superuser's browser until Apply (never in the session or cache).
    """

    wording = forms.CharField(widget=forms.HiddenInput, strip=False)
    fingerprint = forms.CharField(widget=forms.HiddenInput)
    understood = forms.BooleanField(
        required=False,
        label="I understand that the submitted surveys on this version were answered "
        "against the current wording.",
    )

    def __init__(self, *args, version, needs_ack, **kwargs):
        super().__init__(*args, **kwargs)
        self.version = version
        self.needs_ack = needs_ack
        if not needs_ack:
            del self.fields["understood"]

    def clean_understood(self):
        if self.needs_ack and not self.cleaned_data.get("understood"):
            raise ValidationError("Tick the box to confirm.")
        return True

    def clean(self):
        cleaned = super().clean()
        if "wording" in cleaned:
            self.entries = services.parse_questions(cleaned["wording"])
            self.changes, _ = services.compare_questions(self.version, self.entries)
        return cleaned


def _statements(count):
    return f"{count} statement{'' if count == 1 else 's'}"


@admin.register(SurveyVersion)
class SurveyVersionAdmin(admin.ModelAdmin):
    list_display = ("number", "published_at", "question_count")
    inlines = [ReadOnlyQuestions]

    def get_urls(self):
        custom = path(
            "<path:object_id>/load-wording/",
            self.admin_site.admin_view(self.load_wording_view),
            name="survey_surveyversion_load_wording",
        )
        return [custom, *super().get_urls()]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        version = self.get_object(request, object_id)
        if (
            request.user.is_superuser
            and version is not None
            and version == (services.current_version())
        ):
            extra_context["load_wording_url"] = reverse(
                "admin:survey_surveyversion_load_wording", args=[object_id]
            )
        return super().change_view(request, object_id, form_url, extra_context)

    @method_decorator(sensitive_post_parameters("wording"))
    def load_wording_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        version = get_object_or_404(SurveyVersion, pk=object_id)
        back = reverse("admin:survey_surveyversion_change", args=[version.pk])
        if version != services.current_version():
            self.message_user(
                request, "Only the current survey version can be loaded.", messages.ERROR
            )
            return redirect(back)
        drafts = version.responses.filter(status="draft").count()
        submitted = version.responses.filter(status="submitted").count()
        apply_form = None

        if request.method == "POST" and "apply" in request.POST:
            apply_form = ApplyForm(request.POST, version=version, needs_ack=submitted > 0)
            if apply_form.is_valid():
                return self._apply(request, version, apply_form, back)
            if not hasattr(apply_form, "changes"):
                # The hidden copy did not survive the round trip; start again.
                for error in apply_form.non_field_errors():
                    self.message_user(request, error, messages.ERROR)
                return redirect(request.path)
            form, changes = None, apply_form.changes
        elif request.method == "POST":
            form = WordingForm(request.POST, request.FILES, version=version)
            changes = None
            if form.is_valid():
                changes = form.changes
                apply_form = ApplyForm(
                    initial={
                        "wording": json.dumps(form.entries, ensure_ascii=False),
                        "fingerprint": form.fingerprint,
                    },
                    version=version,
                    needs_ack=submitted > 0,
                )
        else:
            form, changes = WordingForm(version=version), None

        context = {
            **self.admin_site.each_context(request),
            "title": f"Load the survey wording into {version}",
            "opts": self.model._meta,
            "version": version,
            "form": form,
            "apply_form": apply_form,
            "changes": changes,
            "drafts": drafts,
            "submitted": submitted,
        }
        return TemplateResponse(request, "admin/survey/surveyversion/load_wording.html", context)

    def _apply(self, request, version, form, back):
        try:
            changes = services.load_questions(
                version, form.entries, expected=form.cleaned_data["fingerprint"]
            )
        except ValidationError as error:
            self.message_user(request, " ".join(error.messages), messages.ERROR)
            return redirect(request.path)
        if not changes.changed:
            self.message_user(request, "Nothing changed: the survey already has this wording.")
            return redirect(back)
        # Counts only: the history must never hold the wording.
        summary = (
            f"Loaded the survey wording: {_statements(changes.reworded)} reworded, "
            f"{_statements(changes.metadata)} with changed extra fields, "
            f"{_statements(changes.unchanged)} unchanged."
        )
        self.log_change(request, version, summary)
        self.message_user(request, summary)
        return redirect(back)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("survey_version", "position", "text")
    list_filter = ("survey_version",)
    readonly_fields = ("survey_version", "position", "text", "min_value", "max_value", "metadata")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
