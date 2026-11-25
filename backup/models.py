from django.conf import settings
from django.db import models


class Empresa(models.Model):
    """Empresa (o sistema é multiempresa: cada uma vê só os próprios backups)."""
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=20)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


class Perfil(models.Model):
    """Liga o usuário à empresa. Só o perfil ADMIN (Gerência) acessa o módulo de backup."""
    TIPOS = [('ADMIN', 'Gerência'), ('FUNCIONARIO', 'Funcionário')]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=20, choices=TIPOS)

    def __str__(self):
        return f'{self.user.username} - {self.empresa.nome}'


from .models_backup import BackupDestino, BackupExecucao, BackupRotina, BackupTesteRestauracao  # noqa: E402,F401
