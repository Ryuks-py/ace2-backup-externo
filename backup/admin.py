from django.contrib import admin

from .models import BackupDestino, BackupExecucao, BackupRotina, BackupTesteRestauracao, Empresa, Perfil

for modelo in (Empresa, Perfil, BackupDestino, BackupRotina, BackupExecucao, BackupTesteRestauracao):
    admin.site.register(modelo)
