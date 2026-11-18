import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from apps.core.storage import private_storage
from apps.core.tenancy import CompanyScopedModel


def upload_letterhead_variant(instance, filename):
    # A random name; the language is in it only to make the stored files easy to tell apart.
    return f'{instance.company_id}/letterhead-{instance.language}-{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class LetterheadVariant(CompanyScopedModel):
    """A letterhead in another language than the company's main one (which lives on the company). A letter is printed on the
    letterhead of its own language, so a company that writes to others in English keeps one in English."""

    language = models.CharField(_('language'), max_length=8, choices=settings.LANGUAGES)
    file = models.ImageField(_('letterhead'), upload_to=upload_letterhead_variant, storage=private_storage)
    source = models.CharField(max_length=10, default='uploaded', editable=False)     # 'uploaded' | 'created'
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'language'], name='one_letterhead_per_language')]
        ordering = ['language']

    def __str__(self):
        return f'{self.company}: {self.language}'


@receiver(post_delete, sender=LetterheadVariant)
def delete_letterhead_file(sender, instance, **kwargs):
    """The stored file leaves with its row (also for the cascade when a company is deleted)."""
    if instance.file:
        instance.file.delete(save=False)
