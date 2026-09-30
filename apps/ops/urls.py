from django.urls import path

from . import views

app_name = 'ops'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('companies/<int:pk>/', views.company_detail, name='company'),
    path('jobs/', views.jobs, name='jobs'),
]
