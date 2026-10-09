"""
Every write to the survey definition goes through here.

Views and commands stay thin: they call one of these functions. A file that does
not describe exactly the questions of the version raises ValidationError before
anything is written, so a bad file can never leave the questions half loaded.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Question, SurveyVersion

# Statements shown on one page of the survey (used from the pages PR onward).
PAGE_SIZE = 5


def current_version():
    """The edition people take now: the one with the highest number."""
    return SurveyVersion.objects.order_by("-number").first()


def _check_entries(version, entries):
    if not isinstance(entries, list):
        raise ValidationError("The file must contain a list of questions.")
    positions = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError("Every entry must be an object with a position and text.")
        position = entry.get("position")
        # bool is an int in Python; true must not pass as position 1.
        if not isinstance(position, int) or isinstance(position, bool):
            raise ValidationError("Every entry needs a whole-number position.")
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError(f"Position {position} needs some text.")
        positions.append(position)
    if sorted(positions) != list(range(1, version.question_count + 1)):
        raise ValidationError(
            f"Positions must be exactly 1 to {version.question_count}, each once "
            f"(got {len(positions)} entries)."
        )


@transaction.atomic
def load_questions(version, entries):
    """
    Set each question's text and metadata from a list of
    {"position", "text", ...extra keys}. Extra keys become the metadata,
    replacing what was there, so loading the same file twice changes nothing and
    a key removed from the file is removed from the database.
    """
    _check_entries(version, entries)
    questions = {q.position: q for q in Question.objects.filter(survey_version=version)}
    changed = []
    for entry in entries:
        question = questions[entry["position"]]
        question.text = entry["text"]
        question.metadata = {k: v for k, v in entry.items() if k not in ("position", "text")}
        changed.append(question)
    Question.objects.bulk_update(changed, ["text", "metadata"])
    return len(changed)
