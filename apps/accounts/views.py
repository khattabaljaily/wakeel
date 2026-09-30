from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from urllib.parse import urlsplit

from .forms import LoginForm, PasswordResetForm, RegisterForm


class LoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('core:dashboard')

    def form_valid(self, form):
        messages.success(self.request, 'تم تغيير كلمة المرور.')
        return super().form_valid(form)


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/password_reset.html'
    form_class = PasswordResetForm
    email_template_name = 'accounts/emails/password_reset.txt'
    subject_template_name = 'accounts/emails/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')

    def form_valid(self, form):
        # Emails link back to the public site address, not whatever host the request came in on.
        site = urlsplit(settings.SITE_URL)
        form.save(
            domain_override=site.netloc, use_https=site.scheme == 'https', request=self.request,
            email_template_name=self.email_template_name, subject_template_name=self.subject_template_name,
            token_generator=self.token_generator, extra_email_context={'site_name': 'وكيل'},
        )
        return redirect(self.success_url)


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')


def register(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    if not settings.ALLOW_REGISTRATION:
        messages.info(request, 'التسجيل مغلق حالياً.')
        return redirect('accounts:login')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user, backend='apps.accounts.backends.EmailOrUsernameBackend')
        return redirect('companies:create')
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def delete_account(request):
    """Delete the user's account, and the companies they own (with everything in them)."""
    from apps.companies.models import Membership

    owned = [m.company for m in request.user.memberships.select_related('company').filter(role=Membership.Role.OWNER)]
    error = ''
    if request.method == 'POST':
        if request.user.check_password(request.POST.get('password', '')):
            for company in owned:
                company.delete()
            user = request.user
            logout(request)
            user.delete()
            messages.success(request, 'تم حذف حسابك وكل بياناته نهائياً.')
            return redirect('core:home')
        error = 'كلمة المرور غير صحيحة.'
    return render(request, 'accounts/delete.html', {'owned': owned, 'error': error})
