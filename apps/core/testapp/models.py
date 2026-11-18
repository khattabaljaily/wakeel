"""Company-scoped model used only by the isolation tests (see settings)."""
from django.db import models

from apps.core.tenancy import CompanyScopedModel


class Note(CompanyScopedModel):
    title = models.CharField(max_length=50)

    class Meta:
        app_label = 'core_testapp'
