"""A stored file leaves with its row. A post_delete signal also runs for queryset deletes and for the cascade when a
company is deleted, which a delete() override on the model would miss."""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Record


@receiver(post_delete, sender=Record)
def delete_record_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
