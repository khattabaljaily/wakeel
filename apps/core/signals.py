"""Clean-up on delete: uploaded/rendered files, and the companies a deleted user owns.

Files: removed when their rows go away.

Connected to post_delete, so it also covers cascades: deleting a company
removes its logo, media library and every post image from disk. Files are
removed only after the transaction commits, so a rolled-back delete keeps them.
"""
from django.db import transaction
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from apps.accounts.models import User
from apps.companies.models import Company, MediaAsset, Membership
from apps.content.models import Post

FILE_FIELDS = {Company: 'logo', MediaAsset: 'file', Post: 'image'}


def _remove_file(field_file):
    if field_file and field_file.name:
        storage, name = field_file.storage, field_file.name
        transaction.on_commit(lambda: storage.delete(name))


@receiver(post_delete)
def delete_files(sender, instance, **kwargs):
    field = FILE_FIELDS.get(sender)
    if field:
        _remove_file(getattr(instance, field))


@receiver(pre_delete, sender=User)
def delete_owned_companies(sender, instance, **kwargs):
    """A user's companies go with them, from any delete path (the Django admin included): each company
    cascades to its plans, posts, media, jobs and accounts, and the file cleanup above removes the files."""
    for company in owned_companies(instance):
        company.delete()


def owned_companies(user):
    return Company.objects.filter(memberships__user=user, memberships__role=Membership.Role.OWNER).distinct()
