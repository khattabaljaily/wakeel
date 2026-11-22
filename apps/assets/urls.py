from django.urls import path

from . import views

app_name = 'assets'

urlpatterns = [
    path('', views.asset_list, name='list'),
    path('new/', views.new, name='new'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/check/', views.check, name='check'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
