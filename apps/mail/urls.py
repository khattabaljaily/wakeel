from django.urls import path

from . import views

app_name = 'mail'

urlpatterns = [
    path('', views.home, name='home'),
    path('box/', views.box, name='box'),
    path('setup/', views.setup, name='setup'),
    path('disconnect/', views.disconnect, name='disconnect'),
    path('compose/', views.compose, name='compose'),
    path('act/', views.act, name='act'),
    path('picker/', views.picker, name='picker'),
    path('preview/', views.preview, name='preview'),
    path('templates/', views.templates, name='templates'),
    path('templates/new/', views.template_new, name='template_new'),
    path('templates/<int:pk>/preview/', views.template_preview, name='template_preview'),
    path('templates/<int:pk>/default/', views.template_default, name='template_default'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('attachment/<int:uid>/<int:index>/', views.attachment, name='attachment'),
    path('attachment/<int:uid>/<int:index>/save/', views.save_attachment, name='save_attachment'),
]
