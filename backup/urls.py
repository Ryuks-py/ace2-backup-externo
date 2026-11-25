from django.urls import path

from . import views
from .acesso import sem_acesso

urlpatterns = [
    path('', views.backup_painel, name='backup_painel'),
    path('historico/', views.backup_historico, name='backup_historico'),
    path('restauracao/', views.backup_restauracao, name='backup_restauracao'),
    path('configuracao/', views.backup_configuracao, name='backup_configuracao'),
    path('rotina/<int:pk>/executar/', views.backup_executar, name='backup_executar'),
    path('sem-acesso/', sem_acesso, name='sem_acesso'),
]
