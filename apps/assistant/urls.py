from django.urls import path

from . import views

app_name = 'assistant'

urlpatterns = [
    path('', views.chat_page, name='chat'),
    path('send/', views.send, name='send'),
    path('proposals/<int:pk>/approve/', views.approve, name='approve'),
    path('proposals/<int:pk>/dismiss/', views.dismiss, name='dismiss'),
    path('clear/', views.clear, name='clear'),
]
