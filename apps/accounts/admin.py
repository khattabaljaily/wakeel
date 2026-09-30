from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class WakeelUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('بيانات إضافية', {'fields': ('phone',)}),)
    list_display = ('username', 'email', 'first_name', 'is_staff', 'date_joined')
