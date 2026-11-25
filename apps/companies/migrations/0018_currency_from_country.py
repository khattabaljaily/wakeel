from django.db import migrations


def fill(apps, schema_editor):
    from apps.money import currencies
    Company = apps.get_model('companies', 'Company')
    for company in Company.objects.filter(currency=''):
        company.currency = currencies.for_country(company.country_code)
        company.save(update_fields=['currency'])


class Migration(migrations.Migration):
    dependencies = [('companies', '0017_company_currency')]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
