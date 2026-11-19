from django.urls import path

from . import letterheads

app_name = 'identity'

urlpatterns = [
    path('', letterheads.page, name='letterheads'),
    path('add/', letterheads.add, name='letterhead_add'),
    path('create/', letterheads.create, name='letterhead_create'),
    path('detect/', letterheads.detect, name='detect'),
    path('main/file/', letterheads.main_file, name='letterhead_main'),
    path('<str:language>/delete/', letterheads.delete, name='letterhead_delete'),
    path('<str:language>/file/', letterheads.file, name='letterhead_file'),
]
