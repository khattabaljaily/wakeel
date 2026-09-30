from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('subscriptions/', views.subscriptions, name='subscriptions'),
    path('subscriptions/new/', views.subscription_create, name='subscription_create'),
    path('subscriptions/<int:pk>/', views.company_detail, name='company'),
    path('subscriptions/<int:pk>/update/', views.subscription_update, name='subscription_update'),
    path('subscriptions/<int:pk>/approve/', views.subscription_approve, name='subscription_approve'),
    path('subscriptions/<int:pk>/renew/', views.subscription_renew, name='subscription_renew'),
    path('subscriptions/<int:pk>/toggle/', views.subscription_toggle, name='subscription_toggle'),
    path('subscriptions/<int:pk>/delete/', views.subscription_delete, name='subscription_delete'),
    path('users/', views.users, name='users'),
    path('users/<int:pk>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),
    path('usage/', views.usage, name='usage'),
    path('jobs/', views.jobs, name='jobs'),
    path('system/', views.system, name='system'),
]
