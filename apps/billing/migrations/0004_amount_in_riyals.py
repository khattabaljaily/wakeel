from django.db import migrations, models


class Migration(migrations.Migration):
    """Payments are in riyals now (the base currency). Rows made earlier keep their dollar amount and their 'USD' currency."""
    dependencies = [('billing', '0003_operator_default_banan')]
    operations = [
        migrations.RenameField('payment', 'amount_usd', 'amount'),
        migrations.AlterField('payment', 'amount', models.DecimalField(max_digits=10, decimal_places=2)),
        migrations.AlterField('payment', 'currency', models.CharField(max_length=3, default='QAR')),
    ]
