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
    path('attachment/<int:uid>/<int:index>/', views.attachment, name='attachment'),
    path('attachment/<int:uid>/<int:index>/save/', views.save_attachment, name='save_attachment'),
]
