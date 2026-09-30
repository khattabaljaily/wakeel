from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class WakeelUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('بيانات إضافية', {'fields': ('phone',)}),)
    list_display = ('username', 'email', 'first_name', 'is_staff', 'date_joined')

    def get_deleted_objects(self, objs, request):
        """The delete confirmation also lists the companies that go with each user (see core.signals)."""
        from apps.core.signals import owned_companies

        to_delete, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        for user in objs:
            for company in owned_companies(user):
                to_delete.append(f'شركة: {company.name} (مع خططها ومنشوراتها وصورها وكل بياناتها)')
                model_count['الشركات'] = model_count.get('الشركات', 0) + 1
        return to_delete, model_count, perms_needed, protected
