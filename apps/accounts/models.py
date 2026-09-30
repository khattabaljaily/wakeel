from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField('البريد الإلكتروني', unique=True)
    phone = models.CharField('رقم الهاتف', max_length=20, blank=True)
    # Self sign-ups wait for a system admin; accounts made any other way are approved.
    is_approved = models.BooleanField('معتمد', default=True)
    approved_at = models.DateTimeField('تاريخ الاعتماد', null=True, blank=True)
    email_notifications = models.BooleanField('إشعارات البريد الإلكتروني', default=True,
                                              help_text='رسائل عند جاهزية الخطط وطلبات التعديل والتعليقات.')

    class Meta:
        verbose_name = 'مستخدم'
        verbose_name_plural = 'المستخدمون'

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def display_name(self):
        return self.first_name or self.username
