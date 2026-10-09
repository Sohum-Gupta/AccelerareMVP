# Data migration. Creates survey version 1 with 25 placeholder questions
# ("Question 1" to "Question 25", scored 1 to 4). The real statements are private
# and never committed: `manage.py load_questions <file>` replaces the text from a
# file kept outside the repository. Safe to re-run: it does nothing if version 1
# already exists.

from django.db import migrations
from django.utils import timezone

QUESTION_COUNT = 25


def create_version_one(apps, schema_editor):
    SurveyVersion = apps.get_model("survey", "SurveyVersion")
    Question = apps.get_model("survey", "Question")

    version, created = SurveyVersion.objects.get_or_create(
        number=1,
        defaults={"published_at": timezone.now(), "question_count": QUESTION_COUNT},
    )
    if not created:
        return
    Question.objects.bulk_create(
        Question(
            survey_version=version, position=n, text=f"Question {n}", min_value=1, max_value=4
        )
        for n in range(1, QUESTION_COUNT + 1)
    )


def delete_version_one(apps, schema_editor):
    # The questions go with it (on_delete=CASCADE).
    apps.get_model("survey", "SurveyVersion").objects.filter(number=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("survey", "0001_schema"),
    ]

    operations = [
        migrations.RunPython(create_version_one, delete_version_one),
    ]
