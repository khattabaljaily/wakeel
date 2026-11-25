"""What Marid can do: the document services, presentations, a question about a document, and creating tasks, notes, contacts
and forms.

Each action validates what the model wrote (the model is never trusted: a document id must belong to this company, a language
must be one of ours, a text has a length limit), says in words what it will do, says what it costs (the platform's own quote,
never the model's), and runs through the same code as the page that does it by hand, so the balance, the refund on failure,
the permissions and the audit trail are the same. The price on the card is the quote of the saved parameters; the approve
button posts it back (`expected_points`) and the charge compares it with the price worked out again, so what is shown is what
is charged. Nothing here runs without the person's approval."""
import datetime
import logging
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.ai import client
from apps.audit import log as audit
from apps.companies.models import Membership
from apps.credits import catalog, charging
from apps.credits import quote as quotes
from apps.credits.middleware import refusal_message
from apps.docops import ops
from apps.docops.models import Operation
from apps.jobs.models import Job
from apps.library.models import Record

logger = logging.getLogger(__name__)
WORKERS = (Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.EDITOR)


class Invalid(ValueError):
    """The parameters cannot be used; the message goes back to the model so it can correct them or ask the person."""


@dataclass
class Action:
    key: str
    title: str                      # shown on the card
    validate: Callable              # (params, request) -> clean params; raises Invalid
    describe: Callable              # (clean) -> [(label, value)] for the card
    price: Callable                 # (clean, request) -> Quote, or None when it is free
    run: Callable                   # (request, clean, expected_points) -> (url, message); raises Invalid when it cannot run now


def _text(params, key, limit, required=False):
    value = ' '.join(str(params.get(key) or '').split()) if limit <= 200 else str(params.get(key) or '').strip()
    if required and not value:
        raise Invalid(f'"{key}" is required.')
    return value[:limit]


def _language(params, key='language'):
    code = str(params.get(key) or '').strip().lower().replace('_', '-')
    code = {'zh': 'zh-hans', 'zh-cn': 'zh-hans'}.get(code, code)
    if code not in dict(settings.LANGUAGES):
        raise Invalid(f'"{key}" must be one of: ' + ', '.join(dict(settings.LANGUAGES)))
    return code


def _int(params, key, low, high, default):
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        raise Invalid(f'"{key}" must be a number.')
    if not low <= value <= high:
        raise Invalid(f'"{key}" must be between {low} and {high}.')
    return value


def _record(params, required=True):
    raw = params.get('document_id')
    if raw in (None, ''):
        if required:
            raise Invalid('"document_id" is required: find the document with search_documents first.')
        return None
    try:
        record = Record.objects.filter(pk=int(raw)).first()
    except (TypeError, ValueError):
        record = None
    if record is None:
        raise Invalid(f'There is no document with id {raw} in this company. Use search_documents to find the right id.')
    return record


def _refused(exc):
    return Invalid(refusal_message(exc))


# ── presentations ────────────────────────────────────────────────────────────────────────────────────────────────────
def _present_validate(params, request):
    from apps.presentations.models import Presentation
    record = _record(params, required=False)
    topic = _text(params, 'topic', 2000)
    if not topic and not record:
        raise Invalid('Give a "topic", or a "document_id" to build the presentation from.')
    tier = str(params.get('quality') or 'premium').lower()
    if tier not in dict(Presentation.TIERS):
        raise Invalid('"quality" must be standard, premium or ultra.')
    return {'topic': topic, 'slides': _int(params, 'slides', Presentation.MIN_SLIDES, Presentation.MAX_SLIDES, 10),
            'language': _language(params), 'quality': tier, 'audience': _text(params, 'audience', 200),
            'tone': _text(params, 'tone', 200), 'document_id': record.pk if record else None}


def _present_price(clean, request):
    from apps.presentations import service
    return service.quote(clean['quality'], clean['slides'], service.source_pages_of(_record(clean, required=False)))


def _present_describe(clean):
    from apps.presentations.models import Presentation
    rows = [(_('Topic'), clean['topic'][:300] or '—'), (_('Quality'), dict(Presentation.TIERS)[clean['quality']]),
            (_('number of slides'), clean['slides']), (_('language of the slides'), dict(settings.LANGUAGES)[clean['language']])]
    if clean['audience']:
        rows.append((_('who will watch it'), clean['audience']))
    if clean['document_id']:
        record = Record.objects.filter(pk=clean['document_id']).first()
        rows.append((_('Document'), record.title if record else '—'))
    return rows


def _present_run(request, clean, expected):
    from apps.presentations import service
    from apps.presentations.models import Presentation
    record = _record(clean, required=False)
    if (reason := service.refusal(request.company, request.user, clean['quality'], clean['slides'], service.source_pages_of(record))):
        raise Invalid(reason)
    made = Presentation(title=(clean['topic'] or (record.title if record else ''))[:60] or _('Presentation'), brief=clean['topic'],
                        language=clean['language'], slides=clean['slides'], tier=clean['quality'], audience=clean['audience'],
                        tone=clean['tone'], source=record)
    try:
        made = service.start(request.company, request.user, made, expected)
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    audit.record(request, 'presentation.created', made.title)
    return reverse('presentations:detail', args=[made.pk]), _('Working on it. This page shows the result as soon as it is ready.')


# ── the document services ────────────────────────────────────────────────────────────────────────────────────────────
SERVICES = {'translate': Operation.TRANSLATE, 'summarize': Operation.SUMMARIZE, 'extract_data': Operation.EXTRACT,
            'to_word': Operation.WORD, 'read_text': Operation.OCR}
SERVICE_NAMES = {'translate': gettext_lazy('Translate a document'), 'summarize': gettext_lazy('Summarize a document'),
                 'extract_data': gettext_lazy('Extract the data of a document'), 'to_word': gettext_lazy('Turn a document into Word'),
                 'read_text': gettext_lazy('Read the text of a document')}


def _doc_validate(params, request):
    name = str(params.get('service') or '')
    if name not in SERVICES:
        raise Invalid('"service" must be one of: ' + ', '.join(SERVICES))
    kind = SERVICES[name]
    record = _record(params)
    tier = str(params.get('option') or 'standard').lower()
    if ops.option_key(kind, tier) is None:
        raise Invalid(f'The option "{tier}" does not exist for {name}: use ' + ', '.join(ops.OPTIONS[kind]) + '.')
    if tier == Operation.PREMIUM and kind in (Operation.TRANSLATE, Operation.WORD) and record.is_image:
        raise Invalid('The original-design option needs a PDF file, and this document is an image.')
    clean = {'service': name, 'document_id': record.pk, 'option': tier, 'language': '', 'length': '', 'source_language': ''}
    if kind in (Operation.TRANSLATE, Operation.SUMMARIZE, Operation.EXTRACT):
        clean['language'] = _language(params)
    if kind == Operation.SUMMARIZE:
        clean['length'] = str(params.get('length') or 'medium').lower()
        if clean['length'] not in dict(Operation.LENGTHS):
            raise Invalid('"length" must be short, medium or detailed.')
    if kind == Operation.TRANSLATE and params.get('source_language'):
        clean['source_language'] = _language(params, 'source_language')
    return clean


def _doc_price(clean, request):
    kind, record = SERVICES[clean['service']], _record(clean)
    if not catalog.is_launched(ops.option_key(kind, clean['option'])):
        raise Invalid('This option is not available yet.')
    pages = ops.page_count(record)
    if pages is None:
        raise Invalid('This document could not be read.')
    return ops.run_quote(record, kind, clean['option'], pages, clean['language'] if kind == Operation.TRANSLATE else '')[0]


def _doc_describe(clean):
    record = Record.objects.filter(pk=clean['document_id']).first()
    tiers = dict(Operation.TIERS)
    rows = [(_('Document'), record.title if record else '—'), (_('Option'), tiers[clean['option']])]
    if clean['language']:
        rows.append((_('Language'), dict(settings.LANGUAGES)[clean['language']]))
    if clean['length']:
        rows.append((_('Length'), dict(Operation.LENGTHS)[clean['length']]))
    return rows


def _doc_run(request, clean, expected):
    record = _record(clean)
    try:
        operation, message = ops.start(request.company, request.user, record, SERVICES[clean['service']], clean['option'],
                                       clean['language'], clean['length'], clean['source_language'], expected)
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    if operation is None:
        raise Invalid(message)
    return reverse('docops:result', args=[operation.pk]), message


# ── a question about one document ──────────────────────────────────────────────────────────────────────────────────
def _ask_validate(params, request):
    record = _record(params)
    return {'document_id': record.pk, 'question': _text(params, 'question', 300, required=True), 'tz': str(params.get('tz') or 'UTC')[:64]}


def _ask_price(clean, request):
    from . import jobs
    _record(clean)
    return quotes.make(jobs.SERVICE)


def _ask_describe(clean):
    record = Record.objects.filter(pk=clean['document_id']).first()
    return [(_('Document'), record.title if record else '—'), (_('Question'), clean['question'])]


def _ask_run(request, clean, expected):
    from . import jobs
    record = _record(clean)
    try:
        Job.enqueue(request.company, Job.Kind.CALL, request.user, expected_points=expected, func=jobs.FUNC, service=jobs.SERVICE,
                    record_id=record.pk, question=clean['question'], tz=clean['tz'], result_url=jobs.result_url())
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    audit.record(request, 'assistant.ask_document', record.title)
    return reverse('notes:list'), _('Reading the document. The answer will be saved as a note.')


# ── tasks, notes, contacts ───────────────────────────────────────────────────────────────────────────────────────────
def _task_validate(params, request):
    from apps.accounts.models import User
    title = _text(params, 'title', 200, required=True)
    due = str(params.get('due_date') or '').strip()
    if due:
        try:
            datetime.date.fromisoformat(due)
        except ValueError:
            raise Invalid('"due_date" must be written YYYY-MM-DD.')
    priority = str(params.get('priority') or 'normal').lower()
    if priority not in ('low', 'normal', 'high'):
        raise Invalid('"priority" must be low, normal or high.')
    email = str(params.get('assignee_email') or '').strip().lower()
    if email and not User.objects.filter(email__iexact=email, memberships__company=request.company, memberships__role__in=WORKERS).exists():
        raise Invalid(f'{email} is not a member of this company who can do tasks. Leave "assignee_email" empty or ask the person.')
    return {'title': title, 'details': _text(params, 'details', 2000), 'priority': priority, 'due_date': due, 'assignee_email': email}


def _task_describe(clean):
    rows = [(_('title'), clean['title'])]
    if clean['details']:
        rows.append((_('details'), clean['details'][:200]))
    rows += [(_('priority'), dict([('low', _('Low')), ('normal', _('Normal')), ('high', _('High'))])[clean['priority']])]
    if clean['due_date']:
        rows.append((_('due date'), clean['due_date']))
    if clean['assignee_email']:
        rows.append((_('assignee'), clean['assignee_email']))
    return rows


def _task_run(request, clean, expected):
    from apps.accounts.models import User
    from apps.tasks.forms import TaskForm
    from apps.tasks.views import _tell_assignee
    assignee = User.objects.filter(email__iexact=clean['assignee_email']).first() if clean['assignee_email'] else None
    form = TaskForm({'title': clean['title'], 'description': clean['details'], 'priority': clean['priority'],
                     'due_date': clean['due_date'], 'assignee': assignee.pk if assignee else ''}, company=request.company)
    if not form.is_valid():
        raise Invalid('; '.join(' '.join(errors) for errors in form.errors.values()))
    task = form.save(commit=False)
    task.created_by = request.user
    task.save()
    audit.record(request, 'task.created', task.title)
    _tell_assignee(request, task)
    return reverse('tasks:detail', args=[task.pk]), _('The task was added.')


def _note_validate(params, request):
    remind = str(params.get('remind_at') or '').strip()
    if remind:
        try:
            datetime.datetime.fromisoformat(remind)
        except ValueError:
            raise Invalid('"remind_at" must be written YYYY-MM-DDTHH:MM.')
    return {'title': _text(params, 'title', 200, required=True), 'text': _text(params, 'text', 4000), 'remind_at': remind,
            'tz': str(params.get('tz') or 'UTC')[:64]}


def _note_describe(clean):
    rows = [(_('title'), clean['title'])]
    if clean['text']:
        rows.append((_('note'), clean['text'][:200]))
    if clean['remind_at']:
        rows.append((_('remind me at'), clean['remind_at'].replace('T', ' ')))
    return rows


def _note_run(request, clean, expected):
    from apps.notes.forms import NoteForm
    day, _sep, clock = clean['remind_at'].partition('T')
    form = NoteForm({'title': clean['title'], 'body': clean['text'], 'remind_date': day, 'remind_time': clock[:5], 'tz': clean['tz']})
    if not form.is_valid():
        raise Invalid('; '.join(' '.join(errors) for errors in form.errors.values()))
    note = form.save(commit=False)
    note.owner = request.user
    note.save()
    return reverse('notes:list'), _('The note was added.')


def _contact_validate(params, request):
    kind = str(params.get('type') or 'client').lower()
    if kind not in ('client', 'supplier', 'partner', 'other'):
        raise Invalid('"type" must be client, supplier, partner or other.')
    return {'name': _text(params, 'name', 200, required=True), 'type': kind, 'company': _text(params, 'company', 200),
            'job_title': _text(params, 'job_title', 120), 'email': _text(params, 'email', 200), 'phone': _text(params, 'phone', 40),
            'notes': _text(params, 'notes', 2000)}


def _contact_describe(clean):
    return [(label, clean[key]) for label, key in ((_('name'), 'name'), (_('company'), 'company'), (_('e-mail'), 'email'),
                                                    (_('phone'), 'phone')) if clean[key]]


def _contact_run(request, clean, expected):
    from apps.contacts.forms import ContactForm
    # The model's own "company" (the contact's firm) is `organization` here: `company` is the company the book belongs to.
    form = ContactForm({'kind': clean['type'], 'name': clean['name'], 'organization': clean['company'], 'job_title': clean['job_title'],
                        'email': clean['email'], 'phone': clean['phone'], 'notes': clean['notes']})
    if not form.is_valid():
        raise Invalid('; '.join(' '.join(errors) for errors in form.errors.values()))
    contact = form.save(commit=False)
    contact.created_by = request.user
    contact.save()
    audit.record(request, 'contact.created', contact.name)
    return reverse('contacts:detail', args=[contact.pk]), _('The contact was added.')


# ── forms ────────────────────────────────────────────────────────────────────────────────────────────────────────────
FORM_KINDS = ('short', 'long', 'choice', 'multi', 'rating', 'date')
FORM_SERVICE = 'create_form'


def _form_validate(params, request):
    questions = []
    for raw in (params.get('questions') or [])[:30]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get('type') or 'short').lower()
        if kind not in FORM_KINDS:
            raise Invalid('A question "type" must be one of: ' + ', '.join(FORM_KINDS))
        options = [' '.join(str(o).split())[:100] for o in (raw.get('options') or []) if str(o).strip()]
        if kind in ('choice', 'multi') and (len(options) < 2 or len(set(options)) != len(options)):
            raise Invalid('A choice question needs at least two different "options".')
        questions.append({'text': _text(raw, 'text', 200, required=True), 'type': kind, 'options': options if kind in ('choice', 'multi') else [],
                          'required': bool(raw.get('required'))})
    if not questions:
        raise Invalid('A form needs at least one question.')
    audience = str(params.get('audience') or 'public').lower()
    if audience not in ('public', 'team'):
        raise Invalid('"audience" must be public or team.')
    return {'title': _text(params, 'title', 200, required=True), 'description': _text(params, 'description', 1000),
            'audience': audience, 'questions': questions}


def _form_describe(clean):
    return [(_('title'), clean['title']), (_('Questions'), '; '.join(q['text'] for q in clean['questions'])[:300])]


def _form_price(clean, request):
    return quotes.make(FORM_SERVICE)


def _form_run(request, clean, expected):
    from apps.forms.models import Form, Question
    quote = _form_price(clean, request)
    form = Form(title=clean['title'], description=clean['description'], audience=clean['audience'], author=request.user)
    try:
        with transaction.atomic():
            charging.charge(request.company, request.user, quote, reference='form', expected_total=expected)
            form.company = request.company
            form.save()
            for position, q in enumerate(clean['questions'], 1):
                Question.objects.create(form=form, position=position, kind=q['type'], text=q['text'], options='\n'.join(q['options']),
                                        required=q['required'])
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    audit.record(request, 'form.created', form.title)
    return reverse('forms:detail', args=[form.pk]), _('The form was created. Check its questions.')


# ── marketing: plans and posts ───────────────────────────────────────────────────────────────────────────────────────
def _plan_validate(params, request):
    from apps.content.forms import month_choices
    from apps.content.models import Platform
    months = dict(month_choices())
    raw = str(params.get('month') or '').strip()[:7]
    month = f'{raw}-01' if len(raw) == 7 else raw
    if month not in months:
        raise Invalid('"month" must be one of (YYYY-MM): ' + ', '.join(m[:7] for m in months))
    platforms = [str(p).lower() for p in (params.get('platforms') or ['facebook', 'instagram'])]
    if not platforms or any(p not in Platform.values for p in platforms):
        raise Invalid('"platforms" must be a list from: ' + ', '.join(Platform.values))
    per_week = _int(params, 'posts_per_week', 1, 10, 4)
    if per_week not in (2, 3, 4, 5, 6, 7, 10):
        raise Invalid('"posts_per_week" must be one of 2, 3, 4, 5, 6, 7, 10.')
    record = _record(params, required=False)
    return {'month': month, 'platforms': list(dict.fromkeys(platforms)), 'posts_per_week': per_week, 'brief': _text(params, 'brief', 2000),
            'document_id': record.pk if record else None}


def _plan_of(clean, request):
    import datetime
    from apps.content.models import ContentPlan
    return ContentPlan(company=request.company, month=datetime.date.fromisoformat(clean['month']), platforms=clean['platforms'],
                       posts_per_week=clean['posts_per_week'], brief=clean['brief'], source=_record(clean, required=False), created_by=request.user)


def _plan_price(clean, request):
    from apps.ai.planner import posts_count
    return quotes.make('generate_plan', posts_count(_plan_of(clean, request)))


def _plan_describe(clean):
    from apps.content.forms import month_choices
    rows = [(_('month'), dict(month_choices())[clean['month']]), (_('platforms'), ', '.join(clean['platforms'])),
            (_('posts per week'), clean['posts_per_week'])]
    if clean['brief']:
        rows.append((_('this month\'s brief'), clean['brief'][:300]))
    if clean['document_id']:
        record = Record.objects.filter(pk=clean['document_id']).first()
        rows.append((_('Document'), record.title if record else '—'))
    return rows


def _plan_run(request, clean, expected):
    from apps.ai.planner import posts_count
    plan = _plan_of(clean, request)
    quote = quotes.make('generate_plan', posts_count(plan))
    try:
        charging.ensure_can_afford(request.company, request.user, quote, expected)
        with transaction.atomic():                  # a refused payment leaves no plan stuck in "generating"
            plan.save()
            Job.enqueue(request.company, Job.Kind.GENERATE_PLAN, request.user, expected_points=quote.total, plan_id=plan.pk)
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    audit.record(request, 'assistant.action', 'content plan')
    return plan.get_absolute_url(), _('Working on it. This page shows the plan as soon as it is ready.')


def _postdoc_validate(params, request):
    return {'document_id': _record(params).pk}


def _postdoc_price(clean, request):
    _record(clean)
    return quotes.make('rewrite_post')


def _postdoc_describe(clean):
    record = Record.objects.filter(pk=clean['document_id']).first()
    return [(_('Document'), record.title if record else '—')]


def _postdoc_run(request, clean, expected):
    from apps.content.services import start_post_from_document
    try:
        post, _job = start_post_from_document(request.company, request.user, _record(clean), expected)
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    return reverse('content:post_edit', args=[post.pk]), _('Writing the post from the document. Refresh the page in a moment.')


def _post_of(params, request):
    from apps.content.models import Post
    try:
        post = Post.objects.filter(pk=int(params.get('post_id')), company=request.company).first()
    except (TypeError, ValueError):
        post = None
    if post is None:
        raise Invalid(f'There is no post with id {params.get("post_id")} in this company. Use search_posts to find the right id.')
    return post


def _rewrite_validate(params, request):
    post = _post_of(params, request)
    return {'post_id': post.pk, 'instruction': _text(params, 'instruction', 1000, required=True)}


def _rewrite_price(clean, request):
    _post_of(clean, request)
    return quotes.make('rewrite_post')


def _rewrite_describe(clean):
    from apps.content.models import Post
    post = Post.objects.filter(pk=clean['post_id']).first()
    return [(_('Post'), post.title if post else '—'), (_('What to change'), clean['instruction'])]


def _rewrite_run(request, clean, expected):
    from apps.content import learning
    from apps.content.models import LearningSignal
    post = _post_of(clean, request)
    try:
        Job.enqueue(request.company, Job.Kind.REWRITE_POST, request.user, expected_points=expected, post_id=post.pk,
                    instruction=clean['instruction'])
    except (charging.InsufficientCredits, charging.PriceChanged) as exc:
        raise _refused(exc)
    learning.record_note(post, LearningSignal.Kind.REWRITE, clean['instruction'])
    return reverse('content:post_edit', args=[post.pk]), _('Rewriting the post. Refresh the page in a moment.')


def _free(clean, request):
    return None


REGISTRY = {a.key: a for a in (
    Action('make_presentation', gettext_lazy('Make a presentation'), _present_validate, _present_describe, _present_price, _present_run),
    Action('document_service', gettext_lazy('Run a document service'), _doc_validate, _doc_describe, _doc_price, _doc_run),
    Action('ask_document', gettext_lazy('Ask about a document'), _ask_validate, _ask_describe, _ask_price, _ask_run),
    Action('create_task', gettext_lazy('Add a task'), _task_validate, _task_describe, _free, _task_run),
    Action('create_note', gettext_lazy('Add a note'), _note_validate, _note_describe, _free, _note_run),
    Action('create_contact', gettext_lazy('Add a contact'), _contact_validate, _contact_describe, _free, _contact_run),
    Action('create_form', gettext_lazy('Create a form'), _form_validate, _form_describe, _form_price, _form_run),
    Action('make_content_plan', gettext_lazy('Make a content plan'), _plan_validate, _plan_describe, _plan_price, _plan_run),
    Action('post_from_document', gettext_lazy('Write a post from a document'), _postdoc_validate, _postdoc_describe, _postdoc_price, _postdoc_run),
    Action('rewrite_post', gettext_lazy('Rewrite a post'), _rewrite_validate, _rewrite_describe, _rewrite_price, _rewrite_run),
)}


def title_of(proposal):
    action = REGISTRY.get(proposal.action)
    if action is None:
        return proposal.action
    if proposal.action == 'document_service':
        return SERVICE_NAMES.get(proposal.params.get('service'), action.title)
    return action.title


def validate(key, params, request):
    """The clean parameters of an action, or Invalid."""
    action = REGISTRY.get(key)
    if action is None:
        raise Invalid('Unknown action "%s". Use one of: %s.' % (key, ', '.join(REGISTRY)))
    return action.validate(params if isinstance(params, dict) else {}, request)


def price_of(proposal, request):
    """The quote the platform will charge for this proposal (None = free); raises when it can no longer be priced."""
    return REGISTRY[proposal.action].price(proposal.params, request)


def card(proposal, request):
    """What the card of a proposal shows: title, details, and the price the platform will charge (`points` is what the approve
    button posts back, and what the charge is compared with)."""
    action = REGISTRY[proposal.action]
    try:
        quote = action.price(proposal.params, request)
        error = ''
    except Exception:                    # a document deleted since, a service switched off
        quote, error = None, _('This can no longer be done: check that the document still exists.')
    points = quote.total if quote else 0
    return {'title': title_of(proposal), 'rows': action.describe(proposal.params), 'price': catalog.money(points),
            'points': points, 'free': not points and not error, 'error': error, 'lines': quote.described() if quote and points else []}


def execute(proposal, request, expected_points=None):
    """Run an approved proposal: (url, message). Raises Invalid with a message the person can read. A paid action is charged
    at the price the card showed (`expected_points`); a free one needs none."""
    action = REGISTRY[proposal.action]
    clean = action.validate(proposal.params, request)          # the world may have changed since it was proposed
    quote = action.price(clean, request)
    if quote and quote.total:
        if expected_points is None:
            raise Invalid(_('Open the card again and approve it from there.'))
    return action.run(request, clean, expected_points)
