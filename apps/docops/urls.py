from django.urls import path

from . import views

app_name = 'docops'

urlpatterns = [
    path('<int:pk>/run/<str:kind>/', views.run, name='run'),
    path('result/<int:pk>/', views.result, name='result'),
    path('result/<int:pk>/delete/', views.delete, name='delete'),
    path('result/<int:pk>/download/<str:fmt>/', views.download, name='download'),
]
