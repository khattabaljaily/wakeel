"""Company isolation for the models that belong to one company (documents, library, forms, tasks ...).

The company the current request or task works for lives in a ContextVar (correct under ASGI and in background
jobs, which set it explicitly with ``company_context``). A model that inherits ``CompanyScopedModel`` refuses to be
queried or saved without one, so a forgotten filter can never leak another company's rows. Use ``for_company`` to be
explicit, or ``all_companies`` for deliberate cross-company work (the platform console).
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_current_company: ContextVar = ContextVar('current_company', default=None)


class CompanyRequired(Exception):
    """A company-scoped query or save ran without a company."""


def get_current_company():
    return _current_company.get()


def set_current_company(company):
    return _current_company.set(company)


def reset_current_company(token):
    _current_company.reset(token)


@contextmanager
def company_context(company):
    token = _current_company.set(company)
    try:
        yield company
    finally:
        _current_company.reset(token)


class CompanyManager(models.Manager):
    def get_queryset(self):
        company = get_current_company()
        if company is None:
            raise CompanyRequired(
                f'{self.model.__name__}.objects needs an active company. Use company_context(), '
                '.for_company(company) or .all_companies.')
        return super().get_queryset().filter(company=company)

    def for_company(self, company):
        return super().get_queryset().filter(company=company)


class CompanyScopedModel(models.Model):
    """Base class for every model that belongs to one company."""

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='+', editable=False)

    objects = CompanyManager()
    all_companies = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.company_id is None:
            company = get_current_company()
            if company is None:
                raise CompanyRequired(f'Cannot save {type(self).__name__} without a company.')
            self.company = company
        super().save(*args, **kwargs)
