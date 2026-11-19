import django.db.models.deletion

import apps.core.storage
import apps.core.testapp.models
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [('companies', '0012_agency')]

    operations = [
        migrations.CreateModel(
            name='Note',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=50)),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='companies.company')),
            ],
            options={'abstract': False},
        ),
        migrations.CreateModel(
            name='Paper',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(blank=True, storage=apps.core.storage.private_storage(), upload_to=apps.core.testapp.models.paper_path)),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='companies.company')),
            ],
            options={'abstract': False},
        ),
    ]
