# Milestone 3, PR 6. A response learns its context: personal (membership empty)
# or one organization (the membership). The new column is nullable, so every
# existing row is a personal attempt, which is what it was, and the code that
# is still running while this migration is applied keeps working. "One open
# draft per account" becomes one per account and context: one rule for the
# personal draft and one per membership.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("enterprises", "0002_deactivated_is_a_member"),
        ("entitlements", "0002_membership_licences"),
        ("responses", "0002_took_before_via"),
        ("survey", "0002_placeholder_questions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="response",
            name="response_one_open_draft_per_account",
        ),
        migrations.AddField(
            model_name="response",
            name="membership",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="responses",
                to="enterprises.membership",
            ),
        ),
        migrations.AddConstraint(
            model_name="response",
            constraint=models.UniqueConstraint(
                condition=models.Q(("membership__isnull", True), ("status", "draft")),
                fields=("account",),
                name="response_one_open_personal_draft",
            ),
        ),
        migrations.AddConstraint(
            model_name="response",
            constraint=models.UniqueConstraint(
                condition=models.Q(("membership__isnull", False), ("status", "draft")),
                fields=("account", "membership"),
                name="response_one_open_draft_per_membership",
            ),
        ),
    ]
