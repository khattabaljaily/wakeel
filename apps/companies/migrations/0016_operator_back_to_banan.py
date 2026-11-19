from django.db import migrations


def to_banan(apps, schema_editor):
    """Wakeel is operated by Banan again (the owner reversed the Jovia decision of 2026-11-19): companies moved to 'jovia' by
    that decision, and those the 0014 backfill gave it, return to the product's default. Past payments keep their operator."""
    apps.get_model('companies', 'Company').objects.filter(operator='jovia').update(operator='banan')


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0015_official_details'),
    ]

    operations = [
        migrations.RunPython(to_banan, migrations.RunPython.noop),
    ]
