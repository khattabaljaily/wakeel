from django import forms
from django.contrib.auth import password_validation

from apps.accounts.models import User
from apps.companies.models import Company

DURATIONS = [('', 'بدون تاريخ انتهاء'), ('14', '14 يوماً (تجربة)'), ('30', 'شهر'), ('90', '3 أشهر'),
             ('180', '6 أشهر'), ('365', 'سنة')]


class SubscriptionEditForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'industry', 'country', 'timezone', 'subscription_plan', 'subscription_expires', 'is_demo']
        widgets = {'subscription_expires': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}


class SubscriptionCreateForm(forms.ModelForm):
    """A subscription made by an admin: the company and its owner's account, approved at once."""

    days = forms.ChoiceField(label='مدة الاشتراك', choices=DURATIONS, required=False, initial='30')
    owner_name = forms.CharField(label='اسم المالك', max_length=150)
    owner_email = forms.EmailField(label='بريد المالك', help_text='إن كان له حساب في وكيل يُضاف إليه، وإلا يُنشأ حساب جديد.')
    owner_password = forms.CharField(label='كلمة المرور', required=False, strip=False,
                                     widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                                     help_text='مطلوبة للحساب الجديد فقط.')

    class Meta:
        model = Company
        fields = ['name', 'industry', 'country', 'timezone', 'description', 'subscription_plan', 'is_demo']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def clean_owner_email(self):
        email = self.cleaned_data['owner_email'].strip().lower()
        self.existing_user = User.objects.filter(email__iexact=email).first()
        if self.existing_user and self.existing_user.is_superuser:
            raise forms.ValidationError('هذا حساب مشرف نظام، ولا يكون مالكاً لاشتراك.')
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('owner_password')
        if cleaned.get('owner_email') and not getattr(self, 'existing_user', None):
            if not password:
                self.add_error('owner_password', 'كلمة المرور مطلوبة لإنشاء حساب المالك.')
            else:
                try:
                    password_validation.validate_password(password, User(email=cleaned['owner_email']))
                except forms.ValidationError as exc:
                    self.add_error('owner_password', exc)
        return cleaned
