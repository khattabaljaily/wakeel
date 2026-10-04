from django.urls import path

from . import views

urlpatterns = [
    path('<str:token>/', views.public_report, name='public_report'),
]
