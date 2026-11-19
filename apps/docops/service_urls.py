from django.urls import path

from . import services

app_name = 'services'

urlpatterns = [
    path('', services.hub, name='hub'),
    path('<str:kind>/', services.start, name='start'),
    path('<str:kind>/<int:pk>/', services.confirm, name='confirm'),
]
