"""The paid jobs of the documents section: write a document, redesign a template, make a template from an uploaded paper,
revise a document. Each is a generic job (`Job.Kind.CALL`): charged when it is queued, at the quote the person was shown
(`expected_points`), and given back if the function raises. What a job makes is named to the page by `result_url`."""
import datetime

from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from apps.ai.client import AIError
from apps.core.tenancy import company_context
from apps.credits import quote as quotes
from apps.jobs.models import Job

from . import generate
from .models import Document, DocumentTemplate

FREE_IMPORTS_PER_DAY = 5
PREFIX = 'apps.documents.jobs.'


def _enqueue(company, user, expected_points, func, services, **params):
    return Job.enqueue(company, Job.Kind.CALL, user, expected_points=expected_points, func=PREFIX + func,
                       services=services, **params)


# --- What each action costs: the screen and the queue use the same functions -----------------------------------

def write_services(template, make_template):
    """The price-list services of writing one document: the fill (a designed template), the writing (a text template), and
    the design of the template as well when there is none yet."""
    fill = generate.FILL_SERVICE if (template is None or template.is_designed) else generate.CONTENT_SERVICE
    return [generate.TEMPLATE_SERVICE, fill] if template is None and make_template else [fill]


def quote_for(services):
    return quotes.bundle(*[quotes.make(name) for name in services])


# --- Write a document --------------------------------------------------------------------------------------------

def queue_write(company, user, expected_points, template, make_template, **params):
    return _enqueue(company, user, expected_points, 'write_document', write_services(template, make_template),
                    template_id=template.pk if template else None, make_template=bool(make_template), **params)


def write_document(job):
    p, company = job.params, job.company
    with company_context(company):
        document = Document(company=company, kind=p['doc_kind'], category=p['category'], language=p['language'], doc_type=p['doc_type'],
                            title=p['doc_type'][:200], recipient=p['recipient'], created_by=job.created_by, status=p['status'])
        template = DocumentTemplate.objects.filter(pk=p['template_id']).first() if p.get('template_id') else None
        if template is None:
            if not p.get('make_template'):
                raise AIError('There is no template of this type.')
            job.set_progress(15, 'Designing the template')
            subject, html = generate.design_html(job, company, p['doc_type'], p['language'], p['doc_kind'], p['instructions'])
            try:
                template = DocumentTemplate.objects.create(
                    company=company, kind=p['doc_kind'], name=p['doc_type'][:200], subject=subject, html=html,
                    category=p['category'], language=p['language'], created_by=job.created_by)
            except IntegrityError:       # somebody made the same type a moment ago: use theirs
                template = DocumentTemplate.objects.get(key=DocumentTemplate.make_key(p['doc_type']), language=p['language'])
        job.set_progress(60, 'Writing the document')
        write = generate.fill_design if template.is_designed else generate.write_from_template
        write(job, document, template, company, p['instructions'])
        document.save()
    job.params = {**p, 'result_url': reverse('documents:edit', args=[document.pk]), 'document_id': document.pk}
    job.save(update_fields=['params'])
    return 'Written. Review it and edit anything you like.'


# --- Redesign a template ------------------------------------------------------------------------------------------

def queue_redesign(company, user, expected_points, template, notes):
    return _enqueue(company, user, expected_points, 'redesign_template', [generate.TEMPLATE_SERVICE],
                    template_id=template.pk, notes=notes[:generate.MAX_INSTRUCTIONS],
                    result_url=reverse('documents:templates'))


def redesign_template(job):
    company = job.company
    with company_context(company):
        template = DocumentTemplate.objects.get(pk=job.params['template_id'])
        notes = job.params.get('notes', '')
        if not template.is_designed and template.body:      # an older text template is designed now, keeping its wording
            notes = (notes + '\n\n' if notes else '') + 'Keep the wording of this text, designed as a page:\n' + template.subject + '\n' + template.body[:12000]
        subject, html = generate.design_html(job, company, template.name, template.language, template.kind, notes, previous=template)
        template.subject, template.html, template.body = subject, html, ''
        template.save()
    return 'The template was redesigned.'


# --- A template made from an uploaded paper (free for the customer, a few a day) -----------------------------------

def imports_left(company):
    since = timezone.now() - datetime.timedelta(days=1)
    used = Job.objects.filter(company=company, kind=Job.Kind.CALL, params__service=generate.IMPORT_SERVICE, created_at__gte=since).count()
    return max(0, FREE_IMPORTS_PER_DAY - used)


def queue_import(company, user, record):
    return Job.enqueue(company, Job.Kind.CALL, user, func=PREFIX + 'import_template', service=generate.IMPORT_SERVICE,
                       record_id=record.pk, result_url=reverse('library:list') + f'?rec={record.pk}')


def import_template(job):
    from apps.library.models import Record
    company = job.company
    with company_context(company):
        record = Record.objects.get(pk=job.params['record_id'])
        subject, html, language = generate.import_design(job, company, record)
        name = (record.doc_type or record.title)[:200]
        language = language or (job.created_by.language if job.created_by_id and job.created_by.language else 'en')
        existing = DocumentTemplate.objects.filter(key=DocumentTemplate.make_key(name), language=language).first()
        if existing is not None:         # the same type again: the template is refreshed from this document, not duplicated
            existing.subject, existing.html, existing.body, existing.category = subject, html, '', record.category
            existing.save()
            template = existing
        else:
            template = DocumentTemplate.objects.create(
                company=company, kind=Document.GENERAL, name=name, subject=subject, html=html, category=record.category,
                language=language, created_by=job.created_by)
    job.params = {**job.params, 'result_url': reverse('library:list') + f'?tpl={template.pk}'}
    job.save(update_fields=['params'])
    return 'The template was made from your document.'


# --- Revise a document --------------------------------------------------------------------------------------------

def queue_rewrite(company, user, expected_points, document, notes):
    service = generate.FILL_SERVICE if document.is_designed else generate.CONTENT_SERVICE
    return _enqueue(company, user, expected_points, 'rewrite_document', [service], document_id=document.pk,
                    notes=notes[:generate.MAX_INSTRUCTIONS], result_url=reverse('documents:edit', args=[document.pk]))


def rewrite_document(job):
    with company_context(job.company):
        document = Document.objects.get(pk=job.params['document_id'])
        (generate.rewrite_values if document.is_designed else generate.rewrite)(job, document, job.params['notes'])
        document.save()
    return 'Done.'
