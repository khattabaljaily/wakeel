from django import forms
from django.contrib.auth import password_validation
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.companies.models import Company

DURATIONS = [('', _('بدون تاريخ انتهاء')), ('14', _('14 يوماً (تجربة)')), ('30', _('شهر')), ('90', _('3 أشهر')),
             ('180', _('6 أشهر')), ('365', _('سنة'))]

DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class SubscriptionEditForm(forms.ModelForm):
    """The subscription's details, as in enjazpms' tenant form (without plans: one offer for everyone)."""

    class Meta:
        model = Company
        fields = ['name', 'industry', 'email', 'phone', 'city', 'country', 'timezone',
                  'subscription_start', 'subscription_expires', 'is_demo']
        widgets = {'subscription_start': DATE, 'subscription_expires': DATE}

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('subscription_start'), cleaned.get('subscription_expires')
        if start and end and end < start:
            self.add_error('subscription_expires', _('نهاية الاشتراك قبل بدايته.'))
        return cleaned


class SubscriptionCreateForm(SubscriptionEditForm):
    """A subscription made by an admin: the company and its owner's account, approved at once."""

    owner_name = forms.CharField(label=_('الاسم الكامل'), max_length=150)
    owner_email = forms.EmailField(label=_('البريد الإلكتروني'), help_text=_('إن كان له حساب في وكيل يُضاف إليه، وإلا يُنشأ حساب جديد.'))
    owner_password = forms.CharField(label=_('كلمة المرور'), required=False, strip=False,
                                     widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                                     help_text=_('مطلوبة للحساب الجديد فقط.'))
    owner_password2 = forms.CharField(label=_('تأكيد كلمة المرور'), required=False, strip=False,
                                      widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    class Meta(SubscriptionEditForm.Meta):
        fields = SubscriptionEditForm.Meta.fields + ['description']
        widgets = {**SubscriptionEditForm.Meta.widgets, 'description': forms.Textarea(attrs={'rows': 2})}

    def clean_owner_email(self):
        email = self.cleaned_data['owner_email'].strip().lower()
        self.existing_user = User.objects.filter(email__iexact=email).first()
        if self.existing_user and self.existing_user.is_superuser:
            raise forms.ValidationError(_('هذا حساب مشرف نظام، ولا يكون مالكاً لاشتراك.'))
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('owner_password')
        if cleaned.get('owner_email') and not getattr(self, 'existing_user', None):
            if not password:
                self.add_error('owner_password', _('كلمة المرور مطلوبة لإنشاء حساب المالك.'))
            elif password != cleaned.get('owner_password2'):
                self.add_error('owner_password2', _('كلمتا المرور غير متطابقتين.'))
            else:
                try:
                    password_validation.validate_password(password, User(email=cleaned['owner_email']))
                except forms.ValidationError as exc:
                    self.add_error('owner_password', exc)
        return cleaned
