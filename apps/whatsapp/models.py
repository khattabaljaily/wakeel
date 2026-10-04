from django.db import models

from apps.companies.models import Company
from apps.content.models import ContentPlan, Post


class ReviewSession(models.Model):
    """A client reviewing one plan over WhatsApp. `awaiting` is the post whose change note the next text message is."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='whatsapp_sessions')
    plan = models.ForeignKey(ContentPlan, on_delete=models.CASCADE, related_name='whatsapp_sessions')
    phone = models.CharField(max_length=20, help_text='Digits only, with the country code.')
    awaiting = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    invited_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['plan', 'phone'], name='one_whatsapp_session_per_plan_phone')]

    def __str__(self):
        return f'{self.phone} · {self.plan_id}'
