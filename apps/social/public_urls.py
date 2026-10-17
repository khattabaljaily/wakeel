from django.urls import path

from . import meta_callbacks

app_name = 'meta_public'

urlpatterns = [
    path('deauthorize/', meta_callbacks.deauthorize, name='deauthorize'),
    path('data-deletion/', meta_callbacks.data_deletion, name='data_deletion'),
    path('data-deletion/status/<str:code>/', meta_callbacks.deletion_status, name='deletion_status'),
]
