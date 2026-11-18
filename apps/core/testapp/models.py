"""Company-scoped model used only by the isolation tests (see settings)."""
from django.db import models

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel


class Note(CompanyScopedModel):
    title = models.CharField(max_length=50)

    class Meta:
        app_label = 'core_testapp'


def paper_path(instance, filename):
    return f'{instance.company_id}/papers/{filename}'


class Paper(CompanyScopedModel):
    """A private file: kept encrypted under its company's id."""
    file = models.FileField(upload_to=paper_path,
                            storage=private_storage(), blank=True)

    class Meta:
        app_label = 'core_testapp'
