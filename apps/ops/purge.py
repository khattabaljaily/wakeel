"""Deleting a company, or a person together with the companies they own, for good.

Everything that belongs to a company goes with it: the rows (every company-scoped table is tied to the company with a
cascading key) and the uploaded files (logos, letterheads, library papers), which a database delete would leave on the
disk. The console asks for the superuser's password first; callers decide who may call this."""
import logging
import os
from pathlib import Path

from django.apps import apps as django_apps
from django.db import models, transaction

from apps.companies.models import Company, Membership
from apps.core.tenancy import CompanyScopedModel

logger = logging.getLogger(__name__)


def company_files(company) -> list:
    """(storage, name) of every uploaded file of this company."""
    found = []
    for model in django_apps.get_models():
        if not issubclass(model, CompanyScopedModel):
            continue
        fields = [f for f in model._meta.get_fields() if isinstance(f, models.FileField)]
        if not fields:
            continue
        for row in model.all_companies.filter(company=company):
            for field in fields:
                file = getattr(row, field.name)
                if file and file.name:
                    found.append((file.storage, file.name))
    return found


def _remove(storage, name) -> bool:
    """Delete one file, then the folders it leaves empty (up to the storage's own root)."""
    try:
        path = Path(storage.path(name))
        storage.delete(name)
    except (OSError, NotImplementedError, ValueError):
        return False
    root = Path(storage.location)
    for folder in path.parents:
        if folder == root or root not in folder.parents:
            break
        try:
            os.rmdir(folder)                      # only succeeds when empty
        except OSError:
            break
    return True


def delete_company(company) -> dict:
    name, pk = company.name, company.pk
    files = company_files(company)
    with transaction.atomic():
        company.delete()
    removed = sum(_remove(storage, file) for storage, file in files)
    logger.warning('Company deleted: id=%s files=%s', pk, removed)
    return {'name': name, 'files': removed}


def owned_companies(user):
    return Company.objects.filter(memberships__user=user, memberships__role=Membership.Role.OWNER).distinct()


def delete_user(user) -> dict:
    """The person and every company they own (whoever else is in it). Memberships elsewhere simply end."""
    email, pk = user.email, user.pk
    companies = [delete_company(c) for c in list(owned_companies(user))]
    user.delete()
    logger.warning('User deleted: id=%s companies=%s', pk, len(companies))
    return {'email': email, 'companies': companies}
