from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Form, Question


class FormForm(forms.ModelForm):
    class Meta:
        model = Form
        fields = ['title', 'description', 'audience', 'closes_on', 'thanks']
        widgets = {'title': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'description': forms.Textarea(attrs={'rows': 3, 'dir': 'auto', 'class': 'form-control'}),
                   'audience': forms.Select(attrs={'class': 'form-select'}),
                   'closes_on': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
                   'thanks': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'})}


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['kind', 'text', 'options', 'required']
        widgets = {'kind': forms.Select(attrs={'class': 'form-select'}),
                   'text': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'options': forms.Textarea(attrs={'rows': 4, 'dir': 'auto', 'class': 'form-control'}),
                   'required': forms.CheckboxInput(attrs={'class': 'form-check-input'})}

    def clean(self):
        data = super().clean()
        if data.get('kind') in Question.WITH_OPTIONS:
            choices = [line.strip() for line in (data.get('options') or '').splitlines() if line.strip()]
            if len(choices) < 2:
                self.add_error('options', _('Write at least two choices, one per line.'))
            elif len(set(choices)) != len(choices):
                self.add_error('options', _('A choice is written twice.'))
            else:
                data['options'] = '\n'.join(choices)
        else:
            data['options'] = ''
        return data
