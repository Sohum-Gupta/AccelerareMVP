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
        changes = services.load_questions(version, sample_entries())
        assert (changes.total, changes.reworded, changes.metadata) == (25, 25, 3)
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
        assert "Loaded 25 questions into survey version 1 (25 changed)" in capsys.readouterr().out
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


def sample_bytes():
    return SAMPLE.read_bytes()


class TestParseQuestions:
    """Reading the file's contents; no database needed."""

    def test_reads_bytes_and_text_the_same(self):
        assert services.parse_questions(sample_bytes()) == sample_entries()
        assert services.parse_questions(sample_bytes().decode()) == sample_entries()

    def test_tolerates_a_byte_order_mark(self):
        assert services.parse_questions(b"\xef\xbb\xbf" + sample_bytes()) == sample_entries()
        assert services.parse_questions("﻿" + sample_bytes().decode()) == sample_entries()

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            (b"\xff\xfe not utf-8", "not UTF-8 text"),
            ("[{]", "not valid JSON"),
            ("", "not valid JSON"),
            ("[" * 100_000 + "]" * 100_000, "nested too deeply"),
            ('[{"position": 1, "text": "x", "weight": NaN}]', "NaN or Infinity"),
            ('[{"position": 1, "text": "x", "weight": -Infinity}]', "NaN or Infinity"),
            ('[{"position": 1, "position": 2, "text": "x"}]', "same key twice"),
            ("[" + "9" * 5000 + "]", "number in it is too long"),
        ],
    )
    def test_refuses_unreadable_input_in_plain_words(self, raw, message):
        with pytest.raises(ValidationError) as caught:
            services.parse_questions(raw)
        assert message in caught.value.messages[0]

    def test_a_json_error_gives_the_place_but_never_the_text(self):
        raw = '[{"position": 1, "text": "Secret wording here" oops}]'
        with pytest.raises(ValidationError) as caught:
            services.parse_questions(raw)
        message = caught.value.messages[0]
        assert "line 1, column" in message
        assert "Secret" not in message and "oops" not in message

    def test_refuses_more_than_the_size_limit(self):
        big = json.dumps([{"position": 1, "text": "x" * services.MAX_FILE_BYTES}])
        for raw in (big, big.encode()):
            with pytest.raises(ValidationError) as caught:
                services.parse_questions(raw)
            assert "larger than 200 KB" in caught.value.messages[0]


def with_entry(position, **changes):
    entries = sample_entries()
    entries[position - 1].update(changes)
    return entries


@pytest.mark.django_db
class TestStorableValues:
    """Values PostgreSQL would refuse (quoting the file in its error) never reach it."""

    @pytest.mark.parametrize(
        "entries",
        [
            with_entry(4, text="Has a \x00 NUL"),
            with_entry(4, text="Broken \ud800 escape"),
            with_entry(4, note="NUL \x00 in metadata"),
            with_entry(4, **{"key\x00": 1}),
            with_entry(4, weight=float("inf")),
            with_entry(4, nested=json.loads("[" * 30 + "]" * 30)),
        ],
    )
    def test_refuses_and_writes_nothing(self, entries):
        version = services.current_version()
        before = snapshot(version)
        with pytest.raises(ValidationError) as caught:
            services.load_questions(version, entries)
        assert caught.value.messages[0].startswith("Position 4 contains something")
        assert snapshot(version) == before

    def test_a_huge_number_from_the_file_is_refused(self):
        entries = services.parse_questions('[{"position": 1, "text": "x", "weight": 1e400}]')
        version = SurveyVersion.objects.create(
            number=2, published_at=timezone.now(), question_count=1
        )
        Question.objects.create(survey_version=version, position=1, text="old")
        with pytest.raises(ValidationError):
            services.load_questions(version, entries)

    def test_refuses_text_over_1000_characters(self):
        with pytest.raises(ValidationError) as caught:
            services.load_questions(services.current_version(), with_entry(9, text="x" * 1001))
        assert caught.value.messages == ["Position 9's text is longer than 1,000 characters."]

    def test_1000_characters_is_fine(self):
        services.load_questions(services.current_version(), with_entry(9, text="x" * 1000))

    def test_a_version_with_missing_rows_gets_a_message_not_a_crash(self):
        version = SurveyVersion.objects.create(
            number=2, published_at=timezone.now(), question_count=2
        )
        Question.objects.create(survey_version=version, position=1, text="only one")
        entries = [{"position": 1, "text": "a"}, {"position": 2, "text": "b"}]
        with pytest.raises(ValidationError) as caught:
            services.load_questions(version, entries)
        assert "should have questions 1 to 2 but has 1" in caught.value.messages[0]


@pytest.mark.django_db
class TestCompareAndConflicts:
    def test_counts_against_the_placeholders(self):
        changes, _ = services.compare_questions(services.current_version(), sample_entries())
        assert changes == services.Changes(total=25, reworded=25, metadata=3, unchanged=0)
        assert changes.changed == 25

    def test_compare_writes_nothing(self):
        version = services.current_version()
        before = snapshot(version)
        services.compare_questions(version, sample_entries())
        assert snapshot(version) == before

    def test_counts_after_loading_and_one_edit(self):
        version = services.current_version()
        services.load_questions(version, sample_entries())
        entries = with_entry(2, text="Edited")
        entries[6]["reverse_scored"] = 1  # was true: equal in Python, still a change
        changes, _ = services.compare_questions(version, entries)
        assert (changes.reworded, changes.metadata, changes.unchanged) == (1, 1, 23)

    def test_applying_twice_changes_nothing_the_second_time(self):
        version = services.current_version()
        _, before = services.compare_questions(version, sample_entries())
        assert services.load_questions(version, sample_entries(), expected=before).changed == 25
        # A double click: the fingerprint is stale but the file changes nothing.
        again = services.load_questions(version, sample_entries(), expected=before)
        assert again.changed == 0

    def test_refuses_when_someone_else_changed_the_wording_since_the_preview(self):
        version = services.current_version()
        _, previewed = services.compare_questions(version, sample_entries())
        services.load_questions(version, with_entry(1, text="Another superuser's file"))
        with pytest.raises(ValidationError) as caught:
            services.load_questions(version, sample_entries(), expected=previewed)
        assert "changed the survey wording after you checked" in caught.value.messages[0]
        assert Question.objects.get(survey_version=version, position=1).text == (
            "Another superuser's file"
        )

    def test_load_locks_the_version_row(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            services.load_questions(services.current_version(), sample_entries())
        assert any(
            "survey_surveyversion" in q["sql"] and "FOR UPDATE" in q["sql"]
            for q in queries.captured_queries
        )


@pytest.mark.django_db
class TestCommandLimits:
    def test_refuses_a_file_over_the_limit(self, tmp_path):
        path = tmp_path / "big.json"
        path.write_bytes(b" " * (services.MAX_FILE_BYTES + 1))
        with pytest.raises(CommandError, match="larger than 200 KB"):
            call_command("load_questions", str(path))
