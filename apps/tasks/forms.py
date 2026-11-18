from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Membership

from .models import Task

MAX_BYTES = 10 * 1024 * 1024
WORKERS = (Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.EDITOR)
User = get_user_model()


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'assignee', 'priority', 'due_date', 'description']
        widgets = {'title': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'assignee': forms.Select(attrs={'class': 'form-select'}),
                   'priority': forms.Select(attrs={'class': 'form-select'}),
                   'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
                   'description': forms.Textarea(attrs={'rows': 4, 'dir': 'auto', 'class': 'form-control'})}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        # Only people who work in this company can be given a task (a client or a viewer cannot do work).
        ids = Membership.objects.filter(company=company, role__in=WORKERS).values_list('user_id', flat=True)
        self.fields['assignee'].queryset = User.objects.filter(pk__in=list(ids)).order_by('first_name', 'email')
        self.fields['assignee'].label_from_instance = lambda u: u.first_name or u.email
        self.fields['assignee'].empty_label = _('Nobody yet')


class AttachmentForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        upload = self.cleaned_data['file']
        if upload.size > MAX_BYTES:
            raise forms.ValidationError(_('The file must be smaller than 10 MB.'))
        return upload
