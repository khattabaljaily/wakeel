from django.contrib import admin

from .models import SocialAccount


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'platform', 'company', 'connected_at', 'last_error')
    exclude = ('access_token', 'refresh_token', 'user_token')
