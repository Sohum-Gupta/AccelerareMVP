"""
Writes to responses go through here (added in the services PR). For now this
holds the one read the admin needs.
"""

from apps.survey.models import Question


def answered_positions(response):
    """Positions of the questions this response has an answer for, never the values."""
    ids = [int(key) for key in response.answers]
    return list(
        Question.objects.filter(survey_version=response.survey_version_id, id__in=ids)
        .order_by("position")
        .values_list("position", flat=True)
    )
