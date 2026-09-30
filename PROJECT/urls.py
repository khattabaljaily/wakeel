from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'إدارة وكيل'
admin.site.site_title = 'وكيل'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('ops/', include('apps.ops.urls')),
    path('accounts/', include('apps.accounts.urls')),
    path('company/social/', include('apps.social.urls')),
    path('company/', include('apps.companies.urls')),
    path('app/', include('apps.content.urls')),
    path('studio/', include('apps.studio.urls')),
    path('api/', include('apps.api.urls')),
    path('review/', include('apps.content.review_urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('', include('apps.core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
