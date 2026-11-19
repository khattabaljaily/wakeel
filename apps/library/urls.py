from django.urls import path

from . import views

app_name = 'library'

urlpatterns = [
    path('', views.record_list, name='list'),
    path('upload/', views.upload, name='upload'),
    path('<int:pk>/', views.edit, name='edit'),
    path('<int:pk>/file/', views.record_file, name='file'),
    path('<int:pk>/read/', views.read, name='read'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
