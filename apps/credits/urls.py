from django.urls import path

from . import views

app_name = 'credits'

urlpatterns = [path('', views.wallet, name='wallet')]
