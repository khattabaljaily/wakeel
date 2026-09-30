from django import forms

from apps.accounts.models import User

from .models import Company, MediaAsset, Membership

COLOR_FIELDS = ('primary_color', 'secondary_color', 'accent_color')


class CompanyForm(forms.ModelForm):
    # Filled by the website autofill: a logo found on the site, downloaded on save
    # unless a file is uploaded.
    logo_url = forms.CharField(required=False, max_length=500, widget=forms.HiddenInput)

    class Meta:
        model = Company
        fields = [
            'name', 'logo', 'industry', 'country', 'city', 'timezone',
            'description', 'products', 'usp', 'target_audience', 'competitors', 'goals',
            'content_language', 'tone', 'voice_notes', 'dos', 'donts', 'brand_hashtags',
            'primary_color', 'secondary_color', 'accent_color', 'heading_font', 'body_font',
            'website', 'phone', 'whatsapp', 'facebook_page', 'instagram_handle', 'tiktok_handle',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'products': forms.Textarea(attrs={'rows': 3}),
            'usp': forms.Textarea(attrs={'rows': 2}),
            'target_audience': forms.Textarea(attrs={'rows': 2}),
            'competitors': forms.Textarea(attrs={'rows': 2}),
            'goals': forms.Textarea(attrs={'rows': 2}),
            'voice_notes': forms.Textarea(attrs={'rows': 2}),
            'dos': forms.Textarea(attrs={'rows': 2}),
            'donts': forms.Textarea(attrs={'rows': 2}),
            'logo': forms.FileInput(attrs={'accept': 'image/*'}),
            **{f: forms.TextInput(attrs={'type': 'color'}) for f in COLOR_FIELDS},
        }

    def clean_instagram_handle(self):
        return self.cleaned_data['instagram_handle'].strip().lstrip('@')

    def clean_tiktok_handle(self):
        return self.cleaned_data['tiktok_handle'].strip().lstrip('@')


class MemberAddForm(forms.Form):
    email = forms.EmailField(label='البريد الإلكتروني')
    role = forms.ChoiceField(label='الدور', choices=[c for c in Membership.Role.choices if c[0] != Membership.Role.OWNER],
                             initial=Membership.Role.EDITOR)

    def __init__(self, *args, company=None, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise forms.ValidationError('لا يوجد مستخدم بهذا البريد. اطلب منه إنشاء حساب في وكيل أولاً.')
        if Membership.objects.filter(company=self.company, user=user).exists():
            raise forms.ValidationError('هذا المستخدم عضو في الشركة بالفعل.')
        self.user = user
        return email


class MediaUploadForm(forms.ModelForm):
    class Meta:
        model = MediaAsset
        fields = ['file', 'title', 'tags']
        widgets = {'file': forms.FileInput(attrs={'accept': 'image/*'})}


class AutopilotForm(forms.ModelForm):
    autopilot_platforms = forms.MultipleChoiceField(label='المنصات', widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        model = Company
        fields = ['autopilot', 'autopilot_day', 'autopilot_posts_per_week', 'autopilot_platforms', 'autopilot_client_email']
        widgets = {'autopilot': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
                   'autopilot_day': forms.NumberInput(attrs={'min': 1, 'max': 28}),
                   'autopilot_client_email': forms.EmailInput(attrs={'dir': 'ltr', 'placeholder': 'client@example.com'})}

    def __init__(self, *args, **kwargs):
        from apps.content.models import Platform
        super().__init__(*args, **kwargs)
        self.fields['autopilot_platforms'].choices = Platform.choices
        self.fields['autopilot_posts_per_week'] = forms.TypedChoiceField(
            label='عدد المنشورات أسبوعياً', coerce=int, choices=[(n, str(n)) for n in (2, 3, 4, 5, 6, 7, 10)])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('autopilot') and not cleaned.get('autopilot_platforms'):
            self.add_error('autopilot_platforms', 'اختر منصة واحدة على الأقل.')
        return cleaned
