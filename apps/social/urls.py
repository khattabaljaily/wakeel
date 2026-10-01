from django.urls import path

from . import views

app_name = 'social'

urlpatterns = [
    path('', views.accounts, name='accounts'),
    path('setup/', views.setup, name='setup'),
    path('meta/connect/', views.meta_connect, name='meta_connect'),
    path('meta/callback/', views.meta_callback, name='meta_callback'),
    path('meta/choose/', views.meta_choose, name='meta_choose'),
    path('tiktok/connect/', views.tiktok_connect, name='tiktok_connect'),
    path('tiktok/callback/', views.tiktok_callback, name='tiktok_callback'),
    path('auto-publish/', views.auto_publish, name='auto_publish'),
    path('<str:platform>/disconnect/', views.disconnect, name='disconnect'),
]
