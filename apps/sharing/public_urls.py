from django.urls import path

from . import public

app_name = 'shared'

urlpatterns = [
    path('<str:token>/', public.open_link, name='open'),
    path('<str:token>/file/', public.file, name='file'),
]
