# Milestone 2, PR 4. The self-report changes from free text ("where did you take
# it") to a three-way choice ("how did you take it": individual, company, other),
# because the product collects no free text until Milestone 5. The old column is
# dropped with whatever it held; no survey page existed yet, so nothing real is lost.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("responses", "0001_response"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="response",
            name="took_before_where",
        ),
        migrations.AddField(
            model_name="response",
            name="took_before_via",
            field=models.CharField(
                blank=True,
                choices=[
                    ("individual", "Individual"),
                    ("company", "Company"),
                    ("other", "Other"),
                ],
                default="",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="response",
            constraint=models.CheckConstraint(
                condition=models.Q(("took_before_via", ""))
                | models.Q(("took_before", True), ("took_before__isnull", False)),
                name="response_took_before_via_only_when_took_before",
            ),
        ),
    ]
