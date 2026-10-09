"""
The survey definition: which questions exist, in which order, on which scale.

A SurveyVersion is one published edition of the questionnaire. Its Questions
belong to it, so a future version 2 is new rows and old responses keep pointing
at the questions they were answered against. The code never knows what a
statement says; it reads the text from here.

All writes go through services.py; the models only describe the shape and the
database rules.
"""

from django.db import models


class SurveyVersion(models.Model):
    number = models.PositiveIntegerField(unique=True)
    published_at = models.DateTimeField()
    # How many questions this version has. services.load_questions checks a file
    # against it, so a version with a different count needs no code change.
    question_count = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="survey_version_number_positive"
            ),
        ]

    def __str__(self):
        return f"Survey version {self.number}"


class Question(models.Model):
    survey_version = models.ForeignKey(
        SurveyVersion, on_delete=models.CASCADE, related_name="questions"
    )
    position = models.PositiveIntegerField()
    text = models.TextField()
    min_value = models.PositiveSmallIntegerField(default=1)
    max_value = models.PositiveSmallIntegerField(default=4)
    # Per-question fields that arrive later (kept in the private file), so each
    # new attribute does not need a migration.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["survey_version", "position"], name="survey_question_unique_position"
            ),
            models.CheckConstraint(
                condition=models.Q(min_value__lte=models.F("max_value")),
                name="survey_question_range_ordered",
            ),
        ]

    def __str__(self):
        return f"v{self.survey_version.number} #{self.position}"
