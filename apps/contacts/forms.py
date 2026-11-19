from django import forms

from .models import Contact, Interaction


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['name', 'kind', 'organization', 'job_title', 'email', 'phone', 'address', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 4}),
                   'email': forms.EmailInput(attrs={'dir': 'ltr'}), 'phone': forms.TextInput(attrs={'dir': 'ltr'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-select' if name == 'kind' else 'form-control'
            if name in ('name', 'organization', 'job_title', 'address', 'notes'):
                field.widget.attrs['dir'] = 'auto'


class InteractionForm(forms.ModelForm):
    class Meta:
        model = Interaction
        fields = ['kind', 'date', 'body']
        widgets = {'kind': forms.Select(attrs={'class': 'form-select'}),
                   'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
                   'body': forms.Textarea(attrs={'rows': 3, 'dir': 'auto', 'class': 'form-control'})}
