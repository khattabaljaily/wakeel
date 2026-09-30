from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('companies/', views.companies, name='companies'),
    path('companies/<int:pk>/', views.company_detail, name='company'),
    path('users/', views.users, name='users'),
    path('users/<int:pk>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),
    path('usage/', views.usage, name='usage'),
    path('jobs/', views.jobs, name='jobs'),
    path('system/', views.system, name='system'),
]
