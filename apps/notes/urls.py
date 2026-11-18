from django.urls import path

from . import views

app_name = 'notes'

urlpatterns = [
    path('', views.note_list, name='list'),
    path('new/', views.new, name='new'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/pin/', views.toggle_pin, name='pin'),
    path('<int:pk>/done/', views.toggle_done, name='done'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
