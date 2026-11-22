from django import forms
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Membership
from apps.library.models import Record

from .models import Asset


class AssetForm(forms.ModelForm):
    # Declared here with an empty list: the papers it offers belong to one company and are filled in when the form is built.
    document = forms.ModelChoiceField(queryset=Record.all_companies.none(), required=False, label=_('document in the library'))

    class Meta:
        model = Asset
        fields = ['kind', 'name', 'provider', 'identifier', 'account', 'start_date', 'expiry_date', 'auto_renew', 'cost',
                  'currency', 'cycle', 'responsible', 'document', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only the company's own members can be made responsible for an asset.
        members = Membership.objects.none() if company is None else company.memberships.select_related('user')
        self.fields['responsible'].queryset = self.fields['responsible'].queryset.filter(
            pk__in=members.values_list('user_id', flat=True))
        self.fields['responsible'].required = False
        # Only the company's own papers can be linked.
        self.fields['document'].queryset = Record.objects.none() if company is None else Record.objects.for_company(company)
        self.fields['document'].required = False
        # The name, provider and domain follow the page's direction (right-to-left in Arabic); the e-mail of the account and the notes
        # follow what is typed.
        for name in ('account', 'notes'):
            self.fields[name].widget.attrs['dir'] = 'auto'
        self.fields['identifier'].widget.attrs['placeholder'] = 'example.com'
        self.fields['currency'].widget.attrs['dir'] = 'ltr'
        self.fields['auto_renew'].widget.attrs['class'] = 'form-check-input'

    def clean_currency(self):
        value = (self.cleaned_data.get('currency') or '').strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise forms.ValidationError(_('Write the 3-letter currency code, for example USD.'))
        return value

    def clean_cost(self):
        cost = self.cleaned_data.get('cost')
        if cost is not None and cost < 0:
            raise forms.ValidationError(_('The cost cannot be negative.'))
        return cost

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('expiry_date')
        if start and end and end < start:
            self.add_error('expiry_date', _('The renewal date cannot be before the start date.'))
        return cleaned
