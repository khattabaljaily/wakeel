from django.urls import path

from . import views

app_name = 'ads'

urlpatterns = [
    path('', views.ad_list, name='list'),
    path('account/', views.choose_account, name='account'),
    path('suggest/<int:post_pk>/', views.suggest, name='suggest'),
    path('<int:pk>/', views.draft_detail, name='draft'),
    path('<int:pk>/create/', views.create, name='create'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
