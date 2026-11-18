from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.companies.decorators import company_required
from apps.credits import charging
from apps.credits import quote as quotes
from apps.credits.jobs import expected_points
from apps.credits.middleware import refusal_message
from apps.documents import qr

from . import answers as answer_tools
from .forms import FormForm, QuestionForm
from .models import Form, Question

SERVICE = 'create_form'
_editors = company_required(edit=True)      # owners, administrators and editors build forms and read the answers; viewers and clients do not


def public_url(request, form):
    """The address people open, built from the host this page was opened on."""
    return request.build_absolute_uri(reverse('fill', args=[form.code]))


def price():
    """The quote of creating a form: the screen and the charge use this same function."""
    return quotes.make(SERVICE)


@_editors
def form_list(request, form=None, open_form=False):
    forms = Form.objects.annotate(answered=Count('responses', distinct=True), asked=Count('questions', distinct=True))
    return render(request, 'forms/list.html', {'forms': forms, 'form': form or FormForm(), 'open_form': open_form, 'quote': price(),
                                               'limit': settings.FORM_MAX_RESPONSES})


@_editors
def new(request):
    """A form is paid once, when it is made, at the price on the button (`expected_points`). The charge and the form are saved
    together: if either fails, neither is kept."""
    form = FormForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        created = form.save(commit=False)
        created.company, created.author = request.company, request.user
        try:
            with transaction.atomic():
                charging.charge(request.company, request.user, price(), reference='form', expected_total=expected_points(request.POST))
                created.save()
        except (charging.InsufficientCredits, charging.PriceChanged) as exc:
            form.add_error(None, refusal_message(exc))
            return form_list(request, form, open_form=True)
        audit.record(request, 'form.created', created.title)
        messages.success(request, _('The form was created. Add its questions.'))
        return redirect('forms:detail', pk=created.pk)
    return form_list(request, form, open_form=True)


def _get(pk):
    return get_object_or_404(Form, pk=pk)


@_editors
def detail(request, pk, question_form=None, open_question=False):
    form = _get(pk)
    url = public_url(request, form)
    return render(request, 'forms/detail.html', {
        'f': form, 'questions': form.questions.all(), 'url': url, 'qr': qr.svg(url), 'answered': form.responses.count(),
        'limit': settings.FORM_MAX_RESPONSES, 'qform': question_form or QuestionForm(), 'open_question': open_question})


@_editors
def edit(request, pk):
    form = _get(pk)
    settings_form = FormForm(request.POST or None, instance=form)
    if request.method == 'POST' and settings_form.is_valid():
        settings_form.save()
        audit.record(request, 'form.updated', form.title)
        messages.success(request, _('Saved.'))
        return redirect('forms:detail', pk=pk)
    return render(request, 'forms/edit.html', {'f': form, 'form': settings_form})


@_editors
@require_POST
def toggle(request, pk):
    form = _get(pk)
    form.is_open = not form.is_open
    form.save(update_fields=['is_open'])
    audit.record(request, 'form.opened' if form.is_open else 'form.closed', form.title)
    messages.success(request, _('The form accepts answers again.') if form.is_open else _('The form is closed.'))
    return redirect('forms:detail', pk=pk)


@_editors
@require_POST
def delete(request, pk):
    form = _get(pk)
    title = form.title
    form.delete()
    audit.record(request, 'form.deleted', title)
    messages.success(request, _('Deleted.'))
    return redirect('forms:list')


@_editors
def question_new(request, pk):
    form = _get(pk)
    qform = QuestionForm(request.POST or None)
    if request.method == 'POST' and qform.is_valid():
        question = qform.save(commit=False)
        question.form, question.company = form, request.company
        question.position = (form.questions.order_by('-position').values_list('position', flat=True).first() or 0) + 1
        question.save()
        return redirect('forms:detail', pk=pk)
    return detail(request, pk, question_form=qform, open_question=True)


@_editors
def question_edit(request, pk, qid):
    form = _get(pk)
    question = get_object_or_404(form.questions, pk=qid)
    qform = QuestionForm(request.POST or None, instance=question)
    if request.method == 'POST' and qform.is_valid():
        qform.save()
        messages.success(request, _('Saved.'))
        return redirect('forms:detail', pk=pk)
    return render(request, 'forms/question_edit.html', {'f': form, 'form': qform, 'question': question,
                                                        'has_answers': question.answers.exists()})


@_editors
@require_POST
def question_move(request, pk, qid):
    form = _get(pk)
    ordered = list(form.questions.all())
    index = next((i for i, q in enumerate(ordered) if q.pk == qid), None)
    if index is not None:
        other = index - 1 if request.POST.get('to') == 'up' else index + 1
        if 0 <= other < len(ordered):
            ordered[index], ordered[other] = ordered[other], ordered[index]
        for i, q in enumerate(ordered):
            if q.position != i:
                Question.objects.filter(pk=q.pk).update(position=i)
    return redirect('forms:detail', pk=pk)


@_editors
@require_POST
def question_delete(request, pk, qid):
    get_object_or_404(_get(pk).questions, pk=qid).delete()
    messages.success(request, _('Deleted.'))
    return redirect('forms:detail', pk=pk)


@_editors
def results(request, pk):
    form = _get(pk)
    responses = form.responses.select_related('user').prefetch_related('answers__question')[:50]
    return render(request, 'forms/results.html', {'f': form, 'summary': answer_tools.summary(form), 'total': form.responses.count(),
                                                  'responses': responses})


@_editors
def results_csv(request, pk):
    form = _get(pk)
    audit.record(request, 'form.exported', form.title)
    response = HttpResponse(answer_tools.to_csv(form), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="form-{form.pk}-answers.csv"'
    response['Cache-Control'] = 'private, no-store'
    return response


@_editors
@require_POST
def response_delete(request, pk, rid):
    get_object_or_404(_get(pk).responses, pk=rid).delete()
    messages.success(request, _('Deleted.'))
    return redirect('forms:results', pk=pk)
