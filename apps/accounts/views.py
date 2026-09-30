from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from urllib.parse import urlsplit

from .forms import LoginForm, PasswordResetForm, RegisterForm
from .models import User


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
        from apps.companies import subscriptions
        from apps.companies.middleware import SESSION_KEY
        from apps.companies.models import Company, Membership
        from apps.companies.views import guess_timezone

        data = form.cleaned_data
        with transaction.atomic():
            user = form.save()
            company = Company.objects.create(
                name=data['company_name'], industry=data['industry'], country=data['country'], phone=data['phone'],
                email=user.email, timezone=guess_timezone(data['country'], [data['phone']]) or 'Asia/Qatar',
            )
            Membership.objects.create(company=company, user=user, role=Membership.Role.OWNER)
        subscriptions.signed_up(company, user)  # awaiting approval; system admins are emailed
        login(request, user, backend='apps.accounts.backends.EmailOrUsernameBackend')
        request.session[SESSION_KEY] = company.pk
        return redirect('companies:status')
    return render(request, 'accounts/register.html', {'form': form})


@login_required
@require_POST
def exit_impersonation(request):
    """Leave a subscriber's workspace entered from the console and return to the system admin account."""
    from apps.ops.views import IMPERSONATOR_KEY

    admin = User.objects.filter(pk=request.session.get(IMPERSONATOR_KEY), is_superuser=True, is_active=True).first()
    if admin is None:
        logout(request)
        return redirect('accounts:login')
    login(request, admin, backend='apps.accounts.backends.EmailOrUsernameBackend')
    return redirect('ops:subscriptions')


@login_required
@require_POST
def email_preferences(request):
    request.user.email_notifications = request.POST.get('email_notifications') == 'on'
    request.user.save(update_fields=['email_notifications'])
    messages.success(request, 'تم تفعيل إشعارات البريد.' if request.user.email_notifications else 'تم إيقاف إشعارات البريد.')
    return redirect('accounts:password_change')


@login_required
def delete_account(request):
    """Delete the user's account, and the companies they own (with everything in them)."""
    from apps.companies.models import Membership

    owned = [m.company for m in request.user.memberships.select_related('company').filter(role=Membership.Role.OWNER)]
    error = ''
    if request.method == 'POST':
        if request.user.check_password(request.POST.get('password', '')):
            user = request.user
            logout(request)
            user.delete()  # its owned companies go with it (core.signals)
            messages.success(request, 'تم حذف حسابك وكل بياناته نهائياً.')
            return redirect('core:home')
        error = 'كلمة المرور غير صحيحة.'
    return render(request, 'accounts/delete.html', {'owned': owned, 'error': error})
