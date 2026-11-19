from django.urls import path

from . import views

app_name = 'brand'

urlpatterns = [
    path('', views.studio, name='studio'),
    path('create/<str:element>/', views.create, name='create'),
    path('kit/start/', views.kit_start, name='kit_start'),
    path('kit/rest/', views.kit_rest, name='kit_rest'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/choose/<int:n>/', views.choose, name='choose'),
    path('<int:pk>/file/<path:name>', views.file, name='file'),
    path('<int:pk>/zip/', views.zip_all, name='zip'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
