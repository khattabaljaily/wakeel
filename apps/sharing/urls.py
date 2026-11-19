from django.urls import path

from . import views

app_name = 'sharing'

urlpatterns = [
    path('', views.listing, name='list'),
    path('new/<str:kind>/<int:pk>/', views.new, name='new'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/revoke/', views.revoke, name='revoke'),
]
