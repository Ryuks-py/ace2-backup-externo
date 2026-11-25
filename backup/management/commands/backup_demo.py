"""Cria a empresa de demonstração, um usuário gestor e 70 dias de histórico fictício de backup.

    python manage.py backup_demo                 # senha do gestor gerada e mostrada no terminal
    python manage.py backup_demo --senha minha   # senha escolhida

Rodar de novo recria o histórico (não duplica a empresa nem o usuário).
"""
import hashlib
import random
import secrets
from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from backup.models import BackupDestino, BackupExecucao, BackupRotina, BackupTesteRestauracao, Empresa, Perfil

DIAS = 70
FALHAS = {   # dias atrás -> (origem, mensagem)
    9: ('ARQUIVOS', 'Tempo esgotado ao enviar ao destino externo (conexão da sede interrompida).'),
    22: ('BANCO', 'Destino recusou a autenticação (credencial expirada). Credencial renovada no mesmo dia.'),
}


class Command(BaseCommand):
    help = 'Cria dados fictícios de demonstração do módulo de backup externo.'

    def add_arguments(self, parser):
        parser.add_argument('--senha', help='Senha do usuário "gestor" (padrão: gerada).')

    def handle(self, *args, **opts):
        rnd = random.Random(20261125)
        hoje = timezone.localdate()
        agora = timezone.localtime()
        tz = timezone.get_current_timezone()

        with transaction.atomic():
            emp, _ = Empresa.objects.get_or_create(cnpj='00.000.000/0001-00',
                                                   defaults={'nome': 'Empresa Alfa (DEMONSTRAÇÃO)'})
            gestor, criado = User.objects.get_or_create(username='gestor', defaults={'first_name': 'Gestor', 'last_name': 'Demo'})
            senha = opts.get('senha') or (secrets.token_urlsafe(9) if criado else None)
            if senha:
                gestor.set_password(senha)
                gestor.save()
            Perfil.objects.update_or_create(user=gestor, defaults={'empresa': emp, 'tipo': 'ADMIN'})

            BackupTesteRestauracao.objects.filter(execucao__rotina__empresa=emp).delete()
            BackupExecucao.objects.filter(rotina__empresa=emp).delete()
            BackupRotina.objects.filter(empresa=emp).delete()
            BackupDestino.objects.filter(empresa=emp).delete()

            destino = BackupDestino.objects.create(empresa=emp, nome='Nuvem — armazenamento de objetos', tipo='S3',
                                                   endereco='s3://exemplo-backup/sistema-rh', retencao_dias=30)
            rotinas = {
                'BANCO': BackupRotina.objects.create(empresa=emp, destino=destino, nome='Banco de dados do Sistema RH',
                                                     origem='BANCO', horario=time(2, 0)),
                'ARQUIVOS': BackupRotina.objects.create(empresa=emp, destino=destino, nome='Arquivos compartilhados da sede',
                                                        origem='ARQUIVOS', horario=time(3, 0)),
            }
            base = {'BANCO': 412 * 1024 ** 2, 'ARQUIVOS': int(3.8 * 1024 ** 3)}
            minutos = {'BANCO': (2, 4), 'ARQUIVOS': (18, 31)}
            ext = {'BANCO': 'sql.gz.enc', 'ARQUIVOS': 'tar.gz.enc'}

            execs = {}
            for atras in range(DIAS, -1, -1):
                dia = hoje - timedelta(days=atras)
                for origem, rotina in rotinas.items():
                    inicio = datetime.combine(dia, rotina.horario).replace(tzinfo=tz) + timedelta(seconds=rnd.randint(3, 40))
                    if inicio > agora:
                        continue
                    crescimento = 1 + (DIAS - atras) * (0.0011 if origem == 'BANCO' else 0.0007)
                    tam = int(base[origem] * crescimento * rnd.uniform(0.995, 1.005))
                    dur = timedelta(minutes=rnd.randint(*minutos[origem]), seconds=rnd.randint(0, 59))
                    falha = FALHAS.get(atras)
                    houve_falha = bool(falha and falha[0] == origem)
                    if houve_falha:
                        BackupExecucao.objects.create(rotina=rotina, inicio=inicio, fim=inicio + dur / 3, status='FALHA',
                                                      mensagem=falha[1])
                        inicio = inicio + timedelta(hours=1)   # nova tentativa automática
                    execs[(origem, atras)] = BackupExecucao.objects.create(
                        rotina=rotina, inicio=inicio, fim=inicio + dur, status='SUCESSO',
                        arquivo=f'{origem.lower()}_{dia:%Y%m%d}_{rotina.horario:%H%M}.{ext[origem]}',
                        tamanho_bytes=tam, hash_sha256=hashlib.sha256(f'{origem}{dia}'.encode()).hexdigest(),
                        mensagem='Nova tentativa automática após falha.' if houve_falha else '',
                        expira_em=dia + timedelta(days=destino.retencao_dias))

            testes = [
                (hoje - timedelta(days=64), 'PARCIAL', 74, 'Banco restaurado, mas os anexos de documentos não abriram: faltava a cópia dos arquivos de mídia. Incluída a pasta media na rotina de arquivos.'),
                (hoje - timedelta(days=35), 'OK', 41, 'Restaurado em servidor de teste. Login, lista de funcionários, contratos e documentos conferidos.'),
            ]
            for data_t, res, mins, obs in testes:
                atras = (hoje - data_t).days + 1
                e = execs.get(('BANCO', atras))
                BackupTesteRestauracao.objects.create(execucao=e, data=data_t, responsavel=gestor, resultado=res,
                                                      tempo_minutos=mins, observacao=obs)

        n = BackupExecucao.objects.filter(rotina__empresa=emp).count()
        self.stdout.write(self.style.SUCCESS(f'Demonstração criada: {n} execuções, 2 testes de restauração.'))
        if senha:
            self.stdout.write(f'Login: gestor / {senha}')
        else:
            self.stdout.write('Usuário "gestor" já existia; senha mantida (use --senha para trocar).')
