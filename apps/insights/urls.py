from django.urls import path

from . import views

app_name = 'insights'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('refresh/', views.refresh, name='refresh'),
    path('repost/<int:pk>/', views.repost, name='repost'),
    path('reports/', views.report_list, name='report_list'),
    path('reports/new/', views.report_create, name='report_create'),
    path('reports/<int:pk>/', views.report_detail, name='report'),
    path('reports/<int:pk>/share/', views.report_share, name='report_share'),
]
