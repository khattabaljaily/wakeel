from django.urls import path

from . import views

app_name = 'forms'

urlpatterns = [
    path('', views.form_list, name='list'),
    path('new/', views.new, name='new'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/toggle/', views.toggle, name='toggle'),
    path('<int:pk>/delete/', views.delete, name='delete'),
    path('<int:pk>/questions/new/', views.question_new, name='question_new'),
    path('<int:pk>/questions/<int:qid>/edit/', views.question_edit, name='question_edit'),
    path('<int:pk>/questions/<int:qid>/move/', views.question_move, name='question_move'),
    path('<int:pk>/questions/<int:qid>/delete/', views.question_delete, name='question_delete'),
    path('<int:pk>/results/', views.results, name='results'),
    path('<int:pk>/results.csv', views.results_csv, name='results_csv'),
    path('<int:pk>/responses/<int:rid>/delete/', views.response_delete, name='response_delete'),
]
