from django.urls import path

from . import views

app_name = 'presentations'

urlpatterns = [
    path('', views.presentation_list, name='list'),
    path('new/', views.new, name='new'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/file/<str:kind>/', views.file, name='file'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
