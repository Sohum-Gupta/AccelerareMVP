"""
Every write to the survey definition goes through here.

Views and commands stay thin: they call one of these functions. A file that does
not describe exactly the questions of the version raises ValidationError before
anything is written, so a bad file can never leave the questions half loaded.

The wording is private, so no message raised here ever quotes it: errors name a
position, a line and column, or a count, never the text.
"""

import hashlib
import json
import math
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Question, SurveyVersion

# Statements shown on one page of the survey (used from the pages PR onward).
PAGE_SIZE = 5

# Limits on a wording file. 25 statements with a few extra fields are a few KB;
# these only catch the wrong file or a runaway paste.
MAX_FILE_BYTES = 200 * 1024
MAX_TEXT_LENGTH = 1000
MAX_METADATA_DEPTH = 20


@dataclass(frozen=True)
class Changes:
    """What a wording file does to a version, in counts only."""

    total: int
    reworded: int
    metadata: int
    unchanged: int

    @property
    def changed(self):
        return self.total - self.unchanged


def current_version():
    """The edition people take now: the one with the highest number."""
    return SurveyVersion.objects.order_by("-number").first()


class _Refused(ValueError):
    pass


def _refuse_constant(name):
    raise _Refused("The file contains NaN or Infinity, which is not a number the survey can use.")


def _no_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        position = dict(pairs).get("position")
        where = f"Position {position}" if isinstance(position, int) else "An object in the file"
        raise _Refused(f"{where} has the same key twice.")
    return dict(pairs)


def parse_questions(raw):
    """
    Turn the file's contents (bytes from an upload or disk, or pasted text) into
    a list of entries, with a plain-English ValidationError for anything that is
    not readable JSON. The shape is checked later, by load_questions.
    """
    if isinstance(raw, bytes):
        if len(raw) > MAX_FILE_BYTES:
            raise ValidationError(_too_big())
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("The file is not UTF-8 text.") from None
    elif len(raw.encode("utf-8", "surrogatepass")) > MAX_FILE_BYTES:
        raise ValidationError(_too_big())
    try:
        return json.loads(
            raw.removeprefix("﻿"),
            parse_constant=_refuse_constant,
            object_pairs_hook=_no_duplicate_keys,
        )
    except _Refused as exc:
        raise ValidationError(str(exc)) from None
    except json.JSONDecodeError as exc:
        # exc.msg says what was expected, never what was found.
        raise ValidationError(
            f"This is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."
        ) from None
    except RecursionError:
        raise ValidationError("This is not valid JSON: it is nested too deeply.") from None
    except ValueError:
        # Python refuses to read a whole number of more than 4,300 digits.
        raise ValidationError("This is not valid JSON: a number in it is too long.") from None


def _too_big():
    return f"The file is larger than {MAX_FILE_BYTES // 1024} KB; check it is the right file."


def _storable(value, depth=0):
    """
    False for anything PostgreSQL would refuse: a NUL character, a broken
    unicode escape, a number that read as infinity, or nesting deep enough to
    exhaust its stack. Its error message would quote part of the file, so these
    are stopped before the database sees them.
    """
    if depth > MAX_METADATA_DEPTH:
        return False
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return "\x00" not in value
    if isinstance(value, dict):
        return all(_storable(k, depth + 1) and _storable(v, depth + 1) for k, v in value.items())
    if isinstance(value, list):
        return all(_storable(v, depth + 1) for v in value)
    if isinstance(value, float):
        return math.isfinite(value)  # 1e400 reads as infinity
    return True


def _metadata(entry):
    return {k: v for k, v in entry.items() if k not in ("position", "text")}


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
        if len(text) > MAX_TEXT_LENGTH:
            raise ValidationError(
                f"Position {position}'s text is longer than {MAX_TEXT_LENGTH:,} characters."
            )
        if not _storable(text) or not _storable(_metadata(entry)):
            raise ValidationError(
                f"Position {position} contains something the database cannot store "
                "(a NUL character, a broken unicode escape, a number too big to "
                "store, or extra fields nested too deeply)."
            )
        positions.append(position)
    if sorted(positions) != list(range(1, version.question_count + 1)):
        raise ValidationError(
            f"Positions must be exactly 1 to {version.question_count}, each once "
            f"(got {len(positions)} entries)."
        )


def _questions_by_position(version):
    questions = {q.position: q for q in Question.objects.filter(survey_version=version)}
    if sorted(questions) != list(range(1, version.question_count + 1)):
        raise ValidationError(
            f"Survey version {version.number} should have questions 1 to "
            f"{version.question_count} but has {len(questions)}; it cannot be loaded."
        )
    return questions


def _canonical(value):
    # In Python true == 1 and 1 == 1.0, so plain != would miss those changes.
    return json.dumps(value, sort_keys=True)


def _compare(questions, entries):
    reworded = metadata = unchanged = 0
    for entry in entries:
        question = questions[entry["position"]]
        new_text = question.text != entry["text"]
        new_metadata = _canonical(question.metadata) != _canonical(_metadata(entry))
        reworded += new_text
        metadata += new_metadata
        unchanged += not (new_text or new_metadata)
    return Changes(len(entries), reworded, metadata, unchanged)


def _fingerprint(questions):
    rows = sorted((q.position, q.text, q.metadata) for q in questions.values())
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def compare_questions(version, entries):
    """
    Check a file and count what applying it would change, without writing
    anything. Returns (Changes, fingerprint): the fingerprint is a hash of the
    wording the counts were made against, for load_questions to compare.
    """
    _check_entries(version, entries)
    questions = _questions_by_position(version)
    return _compare(questions, entries), _fingerprint(questions)


@transaction.atomic
def load_questions(version, entries, expected=None):
    """
    Set each question's text and metadata from a list of
    {"position", "text", ...extra keys}. Extra keys become the metadata,
    replacing what was there, so loading the same file twice changes nothing and
    a key removed from the file is removed from the database. Returns Changes.

    The version row is locked, so two loads never interleave. `expected` is the
    fingerprint the caller previewed against: if the wording changed since then,
    the load is refused, unless the file would change nothing (a double click).
    """
    _check_entries(version, entries)
    SurveyVersion.objects.select_for_update().get(pk=version.pk)
    questions = _questions_by_position(version)
    changes = _compare(questions, entries)
    if changes.changed == 0:
        return changes
    if expected is not None and expected != _fingerprint(questions):
        raise ValidationError(
            "Someone changed the survey wording after you checked this file. Check it again."
        )
    changed = []
    for entry in entries:
        question = questions[entry["position"]]
        question.text = entry["text"]
        question.metadata = _metadata(entry)
        changed.append(question)
    Question.objects.bulk_update(changed, ["text", "metadata"])
    return changes
