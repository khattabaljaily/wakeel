from django.urls import path

from . import views

app_name = 'contacts'

urlpatterns = [
    path('', views.contact_list, name='list'),
    path('new/', views.new, name='new'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/delete/', views.delete, name='delete'),
    path('<int:pk>/log/', views.interaction_add, name='log'),
    path('log/<int:pk>/delete/', views.interaction_delete, name='log_delete'),
]
