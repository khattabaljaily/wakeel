"""The page a form's link or QR code opens. The link is the key (12 random characters), the page is kept out of search
engines and never cached, tries from one address are counted, and a hidden field catches simple robots. A public form
asks nothing about the person; a team form asks them to sign in and keeps one answer each."""
from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from apps.companies.models import Membership
from apps.core import throttle
from apps.core.tenancy import company_context
from apps.notifications.models import Notification
from apps.notifications.services import notify_event

from . import answers as answer_tools
from .models import Answer, Form, Response

VIEWS_PER_MINUTE = (60, 60)
SENDS_PER_TEN_MINUTES = (12, 600)       # answers sent from one address


def _headers(response):
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'same-origin'          # not 'no-referrer': with it the browser posts 'Origin: null' and the CSRF check refuses the form
    return response


def _page(request, template, context, status=200):
    return _headers(render(request, template, context, status=status))


def fill(request, code):
    if throttle.over(request, 'form-view', VIEWS_PER_MINUTE):
        return _page(request, 'forms/fill_message.html', {'kind': 'busy'}, status=429)
    form = Form.all_companies.select_related('company').filter(code=code).first() if 8 <= len(code) <= 24 else None
    if form is None:
        return _page(request, 'forms/fill_message.html', {'kind': 'gone'}, status=404)
    with company_context(form.company):          # the visitor may be in no company, or another one: the form's own is the one that counts
        return _fill(request, form)


def _fill(request, form):
    company = form.company.name_for(translation.get_language() or 'en') or form.company.name
    context = {'f': form, 'company': company, 'questions': list(form.questions.all())}
    if not form.accepting:
        return _page(request, 'forms/fill_message.html', {**context, 'kind': 'closed'})
    if form.responses.count() >= settings.FORM_MAX_RESPONSES:
        return _page(request, 'forms/fill_message.html', {**context, 'kind': 'full'})
    member = None
    if form.audience == Form.TEAM:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?{urlencode({'next': request.path})}")
        member = Membership.objects.filter(company=form.company, user=request.user).exclude(role=Membership.Role.CLIENT).first()
        if member is None:
            return _page(request, 'forms/fill_message.html', {**context, 'kind': 'members'}, status=403)
        if Response.objects.filter(form=form, user=request.user).exists():
            return _page(request, 'forms/fill_message.html', {**context, 'kind': 'done_before'})
    if request.method != 'POST':
        return _page(request, 'forms/fill.html', context)
    if request.POST.get('website'):                       # the hidden field only a robot fills in
        return _page(request, 'forms/fill_message.html', {**context, 'kind': 'thanks'})
    if throttle.over(request, 'form-send', SENDS_PER_TEN_MINUTES):
        return _page(request, 'forms/fill_message.html', {**context, 'kind': 'busy'}, status=429)
    answers, errors = answer_tools.read(form, request.POST)
    if errors or not answers:
        for q in context['questions']:           # what they typed comes back, with what is wrong beside each question
            q.answer, q.picked, q.error = request.POST.get(f'q{q.pk}', ''), request.POST.getlist(f'q{q.pk}'), errors.get(q.pk)
        general = '' if errors else _('Answer at least one question.')
        return _page(request, 'forms/fill.html', {**context, 'general': general}, status=400)
    with transaction.atomic():
        response = Response.objects.create(company=form.company, form=form, user=request.user if member else None)
        Answer.objects.bulk_create([Answer(company=form.company, response=response, question=q, value=v, values=vs) for q, v, vs in answers])
    _tell_the_author(form, request.user if member else None)
    return _page(request, 'forms/fill_message.html', {**context, 'kind': 'thanks'})


def _tell_the_author(form, answered_by):
    """One notification for the person who made the form (not one per answer: while the last one is unread, a new answer
    adds nothing, so a busy form does not bury their bell)."""
    author = form.author
    if author is None or not author.is_active or author == answered_by:
        return
    url = reverse('forms:results', args=[form.pk])
    if Notification.objects.filter(user=author, url=url, read_at__isnull=True).exists():
        return
    notify_event(author, 'form_answer', company=form.company, url=url, title=form.title)
