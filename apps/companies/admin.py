from django.contrib import admin

from .models import Company, MediaAsset, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ('user',)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'industry', 'country', 'content_language', 'created_at')
    search_fields = ('name', 'industry')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [MembershipInline]


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'company', 'created_at')
    list_filter = ('company',)
