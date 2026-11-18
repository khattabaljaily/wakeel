from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('webhook/<slug:operator>/', views.webhook, name='operator_webhook'),
]
