from django.urls import path

from . import views

app_name = 'inbox'

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('refresh/', views.refresh, name='refresh'),
    path('auto-reply/', views.auto_reply, name='auto_reply'),
    path('<int:pk>/reply/', views.item_reply, name='reply'),
    path('<int:pk>/dismiss/', views.item_dismiss, name='dismiss'),
]
