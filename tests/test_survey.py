"""
The survey definition: what the migration created, how current_version picks
an edition, and how load_questions replaces the placeholder wording safely.
Fixtures hold made-up wording only; the real statements are never committed.
"""

import json
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.survey import services
from apps.survey.models import Question, SurveyVersion

SAMPLE = Path(__file__).parent / "fixtures" / "questions_sample.json"


def sample_entries():
    return json.loads(SAMPLE.read_text())


def snapshot(version):
    return list(version.questions.values_list("position", "text", "metadata"))


@pytest.mark.django_db
class TestMigration:
    def test_creates_version_one_with_25_placeholder_questions(self):
        version = SurveyVersion.objects.get(number=1)
        assert version.question_count == 25
        questions = list(version.questions.all())
        assert [q.position for q in questions] == list(range(1, 26))
        assert all(q.min_value == 1 and q.max_value == 4 for q in questions)
        assert [q.text for q in questions] == [f"Question {n}" for n in range(1, 26)]
        assert all(q.metadata == {} for q in questions)

    def test_current_version_is_version_one(self):
        assert services.current_version().number == 1

    def test_current_version_is_the_highest_number(self):
        SurveyVersion.objects.create(number=2, published_at=timezone.now(), question_count=3)
        assert services.current_version().number == 2

    def test_page_size_is_five(self):
        assert services.PAGE_SIZE == 5


@pytest.mark.django_db
class TestDatabaseRules:
    def test_position_is_unique_within_a_version(self):
        version = services.current_version()
        with pytest.raises(IntegrityError), transaction.atomic():
            Question.objects.create(survey_version=version, position=1, text="again")

    def test_version_number_is_unique(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            SurveyVersion.objects.create(number=1, published_at=timezone.now(), question_count=1)

    def test_min_cannot_exceed_max(self):
        version = SurveyVersion.objects.create(
            number=2, published_at=timezone.now(), question_count=1
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Question.objects.create(
                survey_version=version, position=1, text="x", min_value=5, max_value=4
            )


@pytest.mark.django_db
class TestLoadQuestions:
    def test_applies_text_and_metadata(self):
        version = services.current_version()
        assert services.load_questions(version, sample_entries()) == 25
        by_position = {q.position: q for q in version.questions.all()}
        assert by_position[1].text == "Sample statement 1"
        assert by_position[25].text == "Sample statement 25"
        assert by_position[3].metadata == {"theme": "sample-theme-3"}
        assert by_position[7].metadata == {"theme": "sample-theme-7", "reverse_scored": True}
        assert by_position[2].metadata == {}

    def test_is_idempotent(self):
        version = services.current_version()
        services.load_questions(version, sample_entries())
        first = snapshot(version)
        services.load_questions(version, sample_entries())
        assert snapshot(version) == first

    def test_metadata_is_replaced_not_merged(self):
        version = services.current_version()
        services.load_questions(version, sample_entries())
        services.load_questions(version, [{"position": n, "text": f"T{n}"} for n in range(1, 26)])
        assert all(q.metadata == {} for q in version.questions.all())

    def test_refuses_24_entries_and_writes_nothing(self):
        version = services.current_version()
        before = snapshot(version)
        with pytest.raises(ValidationError):
            services.load_questions(version, sample_entries()[:24])
        assert snapshot(version) == before

    def test_refuses_a_duplicate_position_and_writes_nothing(self):
        version = services.current_version()
        before = snapshot(version)
        entries = sample_entries()
        entries[24]["position"] = 24  # 25 entries, but 24 twice and 25 missing
        with pytest.raises(ValidationError):
            services.load_questions(version, entries)
        assert snapshot(version) == before

    @pytest.mark.parametrize(
        "bad",
        [
            {"not": "a list"},
            ["text"],
            [{"position": "1", "text": "x"}],
            [{"position": True, "text": "x"}],
            [{"position": 1, "text": "  "}],
            [{"position": 1}],
        ],
    )
    def test_refuses_malformed_entries(self, bad):
        with pytest.raises(ValidationError):
            services.load_questions(services.current_version(), bad)


@pytest.mark.django_db
class TestCommand:
    def test_runs_via_call_command(self, capsys):
        call_command("load_questions", str(SAMPLE))
        assert "Loaded 25 questions into survey version 1" in capsys.readouterr().out
        assert Question.objects.get(survey_version__number=1, position=1).text == (
            "Sample statement 1"
        )

    def test_refuses_a_bad_file_with_command_error(self, tmp_path):
        path = tmp_path / "short.json"
        path.write_text(json.dumps(sample_entries()[:24]))
        with pytest.raises(CommandError):
            call_command("load_questions", str(path))
        assert Question.objects.filter(text__startswith="Question ").count() == 25

    def test_missing_file_and_bad_json(self, tmp_path):
        with pytest.raises(CommandError):
            call_command("load_questions", str(tmp_path / "nope.json"))
        broken = tmp_path / "broken.json"
        broken.write_text("{not json")
        with pytest.raises(CommandError):
            call_command("load_questions", str(broken))
