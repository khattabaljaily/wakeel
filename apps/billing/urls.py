from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('webhook/', views.default_webhook, name='webhook'),
    path('webhook/<slug:operator>/', views.webhook, name='operator_webhook'),
]
