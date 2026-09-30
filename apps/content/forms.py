import datetime

from django import forms
from django.utils import timezone

from apps.companies.models import MediaAsset
from apps.studio.designs import template_choices

from .models import ContentPlan, Platform, Post

ARABIC_MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']


def month_choices(count=4):
    today = timezone.localdate()
    first = today.replace(day=1)
    choices = []
    for i in range(count):
        month = (first.month - 1 + i) % 12 + 1
        year = first.year + (first.month - 1 + i) // 12
        choices.append((f'{year}-{month:02d}-01', f'{ARABIC_MONTHS[month - 1]} {year}'))
    return choices


class PlanForm(forms.ModelForm):
    month = forms.ChoiceField(label='الشهر')
    platforms = forms.MultipleChoiceField(label='المنصات', choices=Platform.choices, widget=forms.CheckboxSelectMultiple,
                                          initial=[Platform.FACEBOOK, Platform.INSTAGRAM])
    posts_per_week = forms.TypedChoiceField(label='عدد المنشورات أسبوعياً', coerce=int, initial=4,
                                            choices=[(n, str(n)) for n in (2, 3, 4, 5, 6, 7, 10)])

    class Meta:
        model = ContentPlan
        fields = ['month', 'platforms', 'posts_per_week', 'brief']
        widgets = {'brief': forms.Textarea(attrs={'rows': 4, 'placeholder': 'مثال: نطلق خدمة جديدة منتصف الشهر، ولدينا عرض خاص بمناسبة اليوم الوطني…'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['month'].choices = month_choices()
        # Late in the month, the next month is the one worth planning.
        if timezone.localdate().day > 20:
            self.fields['month'].initial = self.fields['month'].choices[1][0]

    def clean_month(self):
        return datetime.date.fromisoformat(self.cleaned_data['month'])


class PostForm(forms.ModelForm):
    platforms = forms.MultipleChoiceField(label='المنصات', choices=Platform.choices, widget=forms.CheckboxSelectMultiple)
    template = forms.ChoiceField(label='القالب', choices=template_choices())
    scheduled_at = forms.DateTimeField(label='موعد النشر', required=False,
                                       widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
                                       input_formats=['%Y-%m-%dT%H:%M'])

    class Meta:
        model = Post
        fields = ['title', 'platforms', 'format', 'scheduled_at', 'pillar', 'caption', 'hashtags',
                  'headline', 'subheadline', 'cta', 'badge', 'template', 'size', 'background', 'video_script', 'visual_notes']
        widgets = {
            'caption': forms.Textarea(attrs={'rows': 8}),
            'video_script': forms.Textarea(attrs={'rows': 8}),
            'visual_notes': forms.Textarea(attrs={'rows': 2}),
            'background': forms.HiddenInput(),
            'format': forms.RadioSelect,
            'size': forms.RadioSelect,
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['background'].queryset = MediaAsset.objects.filter(company=company)
        self.fields['background'].required = False
