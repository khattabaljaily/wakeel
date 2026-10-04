from django.urls import path

from . import views

app_name = 'competitors'

urlpatterns = [
    path('', views.competitor_list, name='list'),
    path('analyse/', views.competitor_analyse, name='analyse'),
    path('<int:pk>/delete/', views.competitor_delete, name='delete'),
]
