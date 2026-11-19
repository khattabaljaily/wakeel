from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.companies.decorators import company_required

from .forms import NoteForm
from .models import Note

_member = company_required(client=True)        # every member keeps their own notes, a viewer and a client too: nobody else sees them


def _mine(request):
    """A member's notes are theirs alone (in this company): every query goes through here."""
    return Note.objects.filter(owner=request.user)


def _list_context(request, form):
    show = request.GET.get('show', 'all')
    notes = _mine(request)
    counts = {'all': notes.exclude(done=True).count(), 'reminders': notes.filter(remind_at__isnull=False, done=False).count(),
              'done': notes.filter(done=True).count()}
    if show == 'reminders':
        notes = notes.filter(remind_at__isnull=False, done=False)
    elif show == 'done':
        notes = notes.filter(done=True)
    else:
        show = 'all'
        notes = notes.exclude(done=True)
    far = timezone.now().replace(year=9000)
    notes = sorted(notes, key=lambda n: (not n.pinned, n.remind_at or far))
    return {'notes': notes, 'show': show, 'counts': counts, 'form': form}


@_member
def note_list(request):
    return render(request, 'notes/list.html', _list_context(request, NoteForm()))


@_member
def new(request):
    form = NoteForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        note = form.save(commit=False)
        note.company, note.owner = request.company, request.user
        note.save()
        messages.success(request, _('The note was added.'))
        return redirect('notes:list')
    return render(request, 'notes/list.html', {**_list_context(request, form), 'open_form': True})


@_member
def edit(request, pk):
    note = get_object_or_404(_mine(request), pk=pk)
    form = NoteForm(request.POST or None, instance=note)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Saved.'))
        return redirect('notes:list')
    return render(request, 'notes/form.html', {'form': form, 'note': note})


def _back(request):
    """Back to the filtered list the button was pressed on; only an address of this site."""
    target = request.POST.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect('notes:list')


def _toggle(field):
    @_member
    @require_POST
    def view(request, pk):
        note = get_object_or_404(_mine(request), pk=pk)
        setattr(note, field, not getattr(note, field))
        note.save(update_fields=[field, 'updated_at'])
        return _back(request)
    view.__name__ = f'toggle_{field}'
    return view


toggle_pin = _toggle('pinned')
toggle_done = _toggle('done')


@_member
@require_POST
def delete(request, pk):
    get_object_or_404(_mine(request), pk=pk).delete()
    messages.success(request, _('Deleted.'))
    return redirect('notes:list')
