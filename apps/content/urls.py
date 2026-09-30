from django.urls import path

from . import review, views

app_name = 'content'

urlpatterns = [
    path('plans/', views.plan_list, name='plan_list'),
    path('plans/new/', views.plan_create, name='plan_create'),
    path('plans/<int:pk>/', views.plan_detail, name='plan_detail'),
    path('plans/<int:pk>/regenerate/', views.plan_regenerate, name='plan_regenerate'),
    path('plans/<int:pk>/delete/', views.plan_delete, name='plan_delete'),
    path('plans/<int:pk>/share/', review.plan_share, name='plan_share'),
    path('plans/<int:pk>/captions.txt', views.post_captions_export, name='plan_captions'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('posts/', views.post_list, name='post_list'),
    path('posts/new/', views.post_create, name='post_create'),
    path('posts/<int:pk>/', views.post_edit, name='post_edit'),
    path('posts/<int:pk>/delete/', views.post_delete, name='post_delete'),
    path('posts/<int:pk>/download/', views.post_download, name='post_download'),
]
