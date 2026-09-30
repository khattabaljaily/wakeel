from django.urls import path

from . import views

app_name = 'api'

urlpatterns = [
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    path('jobs/<int:pk>/cancel/', views.job_cancel, name='job_cancel'),
    path('posts/bulk-status/', views.posts_bulk_status, name='posts_bulk_status'),
    path('posts/bulk-delete/', views.posts_bulk_delete, name='posts_bulk_delete'),
    path('posts/<int:pk>/', views.post_detail, name='post_detail'),
    path('posts/<int:pk>/status/', views.post_status, name='post_status'),
    path('posts/<int:pk>/reschedule/', views.post_reschedule, name='post_reschedule'),
    path('posts/<int:pk>/rewrite/', views.post_rewrite, name='post_rewrite'),
    path('posts/<int:pk>/comments/', views.post_comment, name='post_comment'),
    path('posts/<int:pk>/publish/', views.post_publish, name='post_publish'),
    path('posts/<int:pk>/render/', views.post_render, name='post_render'),
    path('plans/<int:pk>/render/', views.plan_render, name='plan_render'),
]
