# Data migration. allauth keeps its own table of email addresses (one row per
# address per user, with a verified flag) and resolves logins and password
# resets through it. Give every existing email ContactPoint a matching row so
# accounts created before allauth arrived (the production superuser) can log
# in. Verification is copied as it is: an address nobody has proven stays
# unverified in both tables. Safe to re-run.

from django.db import migrations


def backfill(apps, schema_editor):
    ContactPoint = apps.get_model("accounts", "ContactPoint")
    EmailAddress = apps.get_model("account", "EmailAddress")

    for contact in ContactPoint.objects.filter(kind="email").select_related("account"):
        EmailAddress.objects.get_or_create(
            user=contact.account,
            email=contact.value_normalised,
            defaults={
                "primary": contact.is_primary,
                "verified": contact.verified_at is not None,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_backfill_person_and_primary_email"),
        ("account", "0009_emailaddress_unique_primary_email"),
    ]

    operations = [
        # Reverse is a no-op: rolling back allauth's migrations drops its table.
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
