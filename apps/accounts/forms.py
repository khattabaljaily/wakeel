from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.forms import AuthenticationForm

from .models import User


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='البريد الإلكتروني', widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'email'}))
    password = forms.CharField(label='كلمة المرور', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))

    error_messages = {
        'invalid_login': 'البريد الإلكتروني أو كلمة المرور غير صحيحة.',
        'inactive': 'هذا الحساب غير مفعّل.',
    }


class RegisterForm(forms.ModelForm):
    password = forms.CharField(label='كلمة المرور', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    class Meta:
        model = User
        fields = ['first_name', 'email']
        labels = {'first_name': 'الاسم'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('يوجد حساب مسجل بهذا البريد الإلكتروني.')
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password'):
            user = User(email=cleaned.get('email'), first_name=cleaned.get('first_name', ''))
            try:
                password_validation.validate_password(cleaned['password'], user)
            except forms.ValidationError as exc:
                self.add_error('password', exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class PasswordResetForm(auth_forms.PasswordResetForm):
    email = forms.EmailField(label='البريد الإلكتروني', max_length=254,
                             widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email'}))
