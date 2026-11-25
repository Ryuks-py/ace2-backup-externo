"""Módulo de backup externo (protótipo — ACE II).

Destino externo (para onde vão as cópias criptografadas), rotinas (o que copiar e quando),
execuções (o histórico de cada cópia) e testes de restauração (a prova de que a cópia volta).
Os alertas não são gravados: saem do estado atual (ver backup_alertas em views_backup).
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class BackupDestino(models.Model):
    TIPOS = [
        ('S3', 'Armazenamento de objetos (compatível com S3)'),
        ('SFTP', 'Servidor SFTP externo'),
    ]
    empresa = models.ForeignKey('backup.Empresa', on_delete=models.CASCADE, related_name='backup_destinos')
    nome = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=TIPOS, default='S3')
    endereco = models.CharField('Endereço / bucket', max_length=200)
    retencao_dias = models.PositiveSmallIntegerField('Retenção (dias)', default=30)
    criptografia = models.CharField(max_length=30, default='AES-256')
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Destino de backup'
        verbose_name_plural = 'Destinos de backup'

    def __str__(self):
        return self.nome


class BackupRotina(models.Model):
    ORIGENS = [
        ('BANCO', 'Banco de dados do Sistema RH (VPS)'),
        ('ARQUIVOS', 'Arquivos compartilhados (servidor da sede)'),
    ]
    empresa = models.ForeignKey('backup.Empresa', on_delete=models.CASCADE, related_name='backup_rotinas')
    destino = models.ForeignKey(BackupDestino, on_delete=models.PROTECT, related_name='rotinas')
    nome = models.CharField(max_length=80)
    origem = models.CharField(max_length=10, choices=ORIGENS)
    horario = models.TimeField('Horário diário')
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['horario']
        verbose_name = 'Rotina de backup'
        verbose_name_plural = 'Rotinas de backup'

    def __str__(self):
        return self.nome

    @property
    def ultima(self):
        return self.execucoes.order_by('-inicio').first()

    @property
    def ultima_ok(self):
        return self.execucoes.filter(status='SUCESSO').order_by('-inicio').first()


class BackupExecucao(models.Model):
    STATUS = [('SUCESSO', 'Sucesso'), ('FALHA', 'Falha'), ('EM_ANDAMENTO', 'Em andamento')]
    rotina = models.ForeignKey(BackupRotina, on_delete=models.CASCADE, related_name='execucoes')
    inicio = models.DateTimeField()
    fim = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS)
    manual = models.BooleanField(default=False)   # disparada pelo botão "Executar agora"
    arquivo = models.CharField(max_length=200, blank=True)
    tamanho_bytes = models.BigIntegerField(default=0)
    hash_sha256 = models.CharField(max_length=64, blank=True)
    mensagem = models.CharField(max_length=300, blank=True)
    expira_em = models.DateField(null=True, blank=True)   # inicio + retenção do destino

    class Meta:
        ordering = ['-inicio']
        verbose_name = 'Execução de backup'
        verbose_name_plural = 'Execuções de backup'

    def __str__(self):
        return f'{self.rotina} — {self.inicio:%d/%m/%Y %H:%M} — {self.get_status_display()}'

    @property
    def duracao(self):
        if not self.fim:
            return None
        seg = int((self.fim - self.inicio).total_seconds())
        return f'{seg // 60} min {seg % 60:02d} s'

    @property
    def tamanho_legivel(self):
        n = float(self.tamanho_bytes)
        for un in ('B', 'KB', 'MB', 'GB'):
            if n < 1024 or un == 'GB':
                return f'{n:.1f} {un}'.replace('.', ',')
            n /= 1024

    @property
    def expirada(self):
        return bool(self.expira_em and self.expira_em < timezone.localdate())


class BackupTesteRestauracao(models.Model):
    RESULTADOS = [('OK', 'Restaurado com sucesso'), ('PARCIAL', 'Restaurado com ressalvas'), ('FALHOU', 'Não restaurou')]
    execucao = models.ForeignKey(BackupExecucao, on_delete=models.PROTECT, related_name='testes')
    data = models.DateField()
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    resultado = models.CharField(max_length=10, choices=RESULTADOS)
    tempo_minutos = models.PositiveIntegerField('Tempo para restaurar (min)')
    observacao = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data', '-criado_em']
        verbose_name = 'Teste de restauração'
        verbose_name_plural = 'Testes de restauração'

    def __str__(self):
        return f'Teste {self.data:%d/%m/%Y} — {self.get_resultado_display()}'


def prazo_teste(ultimo):
    """Teste de restauração é mensal: vence 30 dias depois do último."""
    return (ultimo.data + timedelta(days=30)) if ultimo else None
