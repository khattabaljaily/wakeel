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
