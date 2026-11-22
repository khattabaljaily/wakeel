from django.urls import path

from . import views

app_name = 'assets_public'

urlpatterns = [
    path('<str:token>.ics', views.public_feed, name='feed'),
]
