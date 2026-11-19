from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read only, even for superusers: the log is evidence."""
    list_display = ('created_at', 'company', 'user_email', 'action', 'target', 'ip')
    list_filter = ('action',)

    def get_queryset(self, request):
        return AuditEvent.all_companies.all()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
