from django.urls import path

from . import views

app_name = 'tasks'

urlpatterns = [
    path('', views.task_list, name='list'),
    path('new/', views.new, name='new'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/status/', views.set_status, name='status'),
    path('<int:pk>/delete/', views.delete, name='delete'),
    path('<int:pk>/comment/', views.comment, name='comment'),
    path('<int:pk>/attach/', views.attach, name='attach'),
    path('files/<int:pk>/', views.attachment_file, name='file'),
    path('files/<int:pk>/delete/', views.attachment_delete, name='file_delete'),
]
