"""The Word file of a result leaves with its row (also on the cascade when the document or the workspace is deleted)."""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Operation


@receiver(post_delete, sender=Operation)
def delete_result_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
