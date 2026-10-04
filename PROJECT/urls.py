from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from django.views.i18n import JavaScriptCatalog

admin.site.site_header = _('إدارة وكيل')
admin.site.site_title = _('وكيل')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('jsi18n/', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    path('ops/', include('apps.ops.urls')),
    path('accounts/', include('apps.accounts.urls')),
    path('company/social/', include('apps.social.urls')),
    path('company/', include('apps.companies.urls')),
    path('app/', include('apps.content.urls')),
    path('app/insights/', include('apps.insights.urls')),
    path('app/competitors/', include('apps.insights.competitor_urls')),
    path('app/inbox/', include('apps.inbox.urls')),
    path('app/ads/', include('apps.ads.urls')),
    path('report/', include(('apps.insights.public_urls', 'insights_public'))),
    path('whatsapp/', include('apps.whatsapp.urls')),
    path('studio/', include('apps.studio.urls')),
    path('api/', include('apps.api.urls')),
    path('review/', include('apps.content.review_urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('', include('apps.core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
