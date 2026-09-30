from django.urls import path

from . import views

app_name = 'companies'

urlpatterns = [
    path('new/', views.create, name='create'),
    path('status/', views.status, name='status'),
    path('brand/', views.brand, name='brand'),
    path('brand/lessons/', views.lessons, name='lessons'),
    path('autopilot/', views.autopilot, name='autopilot'),
    path('autofill/', views.autofill, name='autofill'),
    path('delete/', views.delete_company, name='delete'),
    path('leave/', views.leave_company, name='leave'),
    path('switch/<int:pk>/', views.switch, name='switch'),
    path('team/', views.team, name='team'),
    path('team/<int:pk>/', views.member_update, name='member_update'),
    path('media/', views.media, name='media'),
    path('media/<int:pk>/delete/', views.media_delete, name='media_delete'),
]
