from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    email = models.EmailField(_('البريد الإلكتروني'), unique=True)
    phone = models.CharField(_('رقم الهاتف'), max_length=20, blank=True)
    # Self sign-ups wait for a system admin; accounts made any other way are approved.
    is_approved = models.BooleanField(_('معتمد'), default=True)
    approved_at = models.DateTimeField(_('تاريخ الاعتماد'), null=True, blank=True)
    language = models.CharField(_('اللغة'), max_length=5, blank=True, choices=settings.LANGUAGES)
    email_notifications = models.BooleanField(_('إشعارات البريد الإلكتروني'), default=True,
                                              help_text=_('رسائل عند جاهزية الخطط وطلبات التعديل والتعليقات.'))

    class Meta:
        verbose_name = _('مستخدم')
        verbose_name_plural = _('المستخدمون')

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def display_name(self):
        return self.first_name or self.username
