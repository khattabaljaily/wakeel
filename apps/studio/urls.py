from django.urls import path

from . import views

app_name = 'studio'

urlpatterns = [
    path('preview/<int:pk>/', views.preview, name='preview'),
]
