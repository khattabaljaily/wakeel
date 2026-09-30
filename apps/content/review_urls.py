from django.urls import path

from . import review

app_name = 'review'

urlpatterns = [
    path('<str:token>/', review.plan_review, name='plan'),
    path('<str:token>/posts/<int:pk>/', review.post_feedback, name='feedback'),
]
