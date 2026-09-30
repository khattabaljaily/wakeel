from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('manifest.webmanifest', views.manifest, name='manifest'),
    path('sw.js', views.service_worker, name='service_worker'),
    path('offline/', views.offline, name='offline'),
    path('app/', views.dashboard, name='dashboard'),
]
