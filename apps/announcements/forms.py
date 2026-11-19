from django import forms

from .models import Announcement


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['kind', 'title', 'body', 'requires_ack']
        widgets = {'kind': forms.Select(attrs={'class': 'form-select'}),
                   'title': forms.TextInput(attrs={'dir': 'auto', 'class': 'form-control'}),
                   'body': forms.Textarea(attrs={'rows': 7, 'dir': 'auto', 'class': 'form-control'}),
                   'requires_ack': forms.CheckboxInput(attrs={'class': 'form-check-input'})}
