from django.db import migrations

# The founder's placeholder prices of 2026-11-13: 1, 2 and 3 dollars for Tiers
# 1, 2 and 3. Staff change them in the admin; this only makes sure the three
# rows exist. It never overwrites a price that is already there.
STARTING_PRICES = {1: 100, 2: 200, 3: 300}


def create_prices(apps, schema_editor):
    Price = apps.get_model("payments", "Price")
    for tier, cents in STARTING_PRICES.items():
        Price.objects.get_or_create(tier=tier, defaults={"amount_cents": cents})


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        # Going backwards leaves the rows: the table itself is dropped by 0001.
        migrations.RunPython(create_prices, migrations.RunPython.noop),
    ]
