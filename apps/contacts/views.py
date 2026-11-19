from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.audit import log as audit
from apps.companies.decorators import company_required
from apps.companies.models import Membership

from .forms import ContactForm, InteractionForm
from .models import Contact, Interaction


def _member(view):
    """The company's own people read the book; an outside client of the company does not see its clients and suppliers."""
    @company_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.membership.role == Membership.Role.CLIENT:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


_editor = company_required(edit=True)        # viewers read; owners, administrators and editors change things


def _list_context(request, form):
    kind = request.GET.get('kind', '')
    q = request.GET.get('q', '').strip()[:100]
    everyone = Contact.objects.all()
    per_kind = dict(everyone.order_by().values_list('kind').annotate(n=Count('id')))
    contacts = everyone.filter(kind=kind) if kind in dict(Contact.KINDS) else everyone
    if q:
        contacts = contacts.filter(Q(name__icontains=q) | Q(organization__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
    return {'contacts': contacts, 'kind': kind if kind in dict(Contact.KINDS) else '', 'q': q,
            'kinds': [(k, label, per_kind.get(k, 0)) for k, label in Contact.KINDS], 'total': sum(per_kind.values()),
            'can_edit': request.membership.can_edit, 'form': form}


@_member
def contact_list(request):
    kind = request.GET.get('kind', '')
    form = ContactForm(initial={'kind': kind if kind in dict(Contact.KINDS) else Contact.CLIENT})
    return render(request, 'contacts/list.html', _list_context(request, form))


@_editor
def new(request):
    form = ContactForm(request.POST or None, initial={'kind': request.GET.get('kind', Contact.CLIENT)})
    if request.method == 'POST' and form.is_valid():
        contact = form.save(commit=False)
        contact.company, contact.created_by = request.company, request.user
        contact.save()
        audit.record(request, 'contact.created', contact.name)
        messages.success(request, _('The contact was added.'))
        return redirect('contacts:detail', pk=contact.pk)
    return render(request, 'contacts/list.html', {**_list_context(request, form), 'open_form': True})


@_editor
def edit(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit.record(request, 'contact.updated', contact.name)
        messages.success(request, _('Saved.'))
        return redirect('contacts:detail', pk=contact.pk)
    return render(request, 'contacts/form.html', {'form': form, 'contact': contact})


def _can_delete(request, contact):
    return request.membership.can_manage or (request.membership.can_edit and contact.created_by_id == request.user.pk)


@_member
def detail(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    return render(request, 'contacts/detail.html', {
        'contact': contact, 'interactions': contact.interactions.select_related('author'), 'form': InteractionForm(),
        'can_edit': request.membership.can_edit, 'can_manage': request.membership.can_manage,
        'can_delete': _can_delete(request, contact)})


@_editor
@require_POST
def delete(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if not _can_delete(request, contact):
        raise PermissionDenied
    name = contact.name
    contact.delete()
    audit.record(request, 'contact.deleted', name)
    messages.success(request, _('Deleted.'))
    return redirect('contacts:list')


@_editor
@require_POST
def interaction_add(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    form = InteractionForm(request.POST)
    if form.is_valid() and form.cleaned_data['body'].strip():
        item = form.save(commit=False)
        item.company, item.contact, item.author = request.company, contact, request.user
        item.save()
    else:
        messages.error(request, _('Write what happened.'))
    return redirect('contacts:detail', pk=contact.pk)


@_editor
@require_POST
def interaction_delete(request, pk):
    item = get_object_or_404(Interaction, pk=pk)
    if not (request.membership.can_manage or item.author_id == request.user.pk):
        raise PermissionDenied
    contact_pk = item.contact_id
    item.delete()
    return redirect('contacts:detail', pk=contact_pk)
