from django.urls import path

from . import views

app_name = 'whatsapp'

urlpatterns = [
    path('webhook/', views.webhook, name='webhook'),
    path('plans/<int:pk>/send/', views.send_plan, name='send_plan'),
]
