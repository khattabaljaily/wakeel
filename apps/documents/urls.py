from django.urls import path

from . import views

app_name = 'documents'

urlpatterns = [
    path('issued/', views.issued, name='issued'),
    path('templates/', views.template_list, name='templates'),
    path('templates/import/<int:pk>/', views.template_import, name='template_import'),
    path('templates/<int:pk>/pdf/', views.template_pdf, name='template_pdf'),
    path('templates/<int:pk>/preview/', views.template_preview, name='template_preview'),
    path('templates/save/<int:pk>/', views.template_save, name='template_save'),
    path('templates/<int:pk>/use/', views.template_use, name='template_use'),
    path('templates/<int:pk>/redesign/', views.template_redesign, name='template_redesign'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('working/<int:pk>/', views.working, name='working'),
    path('new/<str:kind>/', views.new, name='new'),
    path('<int:pk>/', views.edit, name='edit'),
    path('<int:pk>/print/', views.print_view, name='print'),
    path('<int:pk>/pdf/', views.download_pdf, name='pdf'),
    path('<int:pk>/docx/', views.download_docx, name='docx'),
    path('<int:pk>/email/', views.email_document, name='email'),
    path('<int:pk>/submit/', views.submit, name='submit'),
    path('<int:pk>/review/', views.review, name='review'),
    path('<int:pk>/rewrite/', views.rewrite, name='rewrite'),
    path('<int:pk>/values/', views.values, name='values'),
    path('<int:pk>/revoke/', views.revoke, name='revoke'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
