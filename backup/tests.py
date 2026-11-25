from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Empresa, Perfil
from .models_backup import BackupDestino, BackupExecucao, BackupRotina, BackupTesteRestauracao
from .views import backup_alertas


class BackupTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Empresa A', cnpj='1')
        self.outra = Empresa.objects.create(nome='Empresa B', cnpj='2')
        self.admin = User.objects.create_user('adm', password='x')
        Perfil.objects.create(user=self.admin, empresa=self.empresa, tipo='ADMIN')
        self.func = User.objects.create_user('func', password='x')
        Perfil.objects.create(user=self.func, empresa=self.empresa, tipo='FUNCIONARIO')
        self.destino = BackupDestino.objects.create(empresa=self.empresa, nome='Nuvem', endereco='s3://x')
        self.rotina = BackupRotina.objects.create(empresa=self.empresa, destino=self.destino, nome='Banco',
                                                  origem='BANCO', horario=time(2, 0))
        self.client.force_login(self.admin)

    def _exec(self, status='SUCESSO', horas_atras=2, rotina=None, **kw):
        inicio = timezone.now() - timedelta(hours=horas_atras)
        return BackupExecucao.objects.create(rotina=rotina or self.rotina, inicio=inicio, fim=inicio + timedelta(minutes=3),
                                             status=status, tamanho_bytes=1024 ** 2, **kw)

    def _titulos(self):
        return [a['titulo'] for a in backup_alertas(self.empresa)]

    def test_sem_execucao_e_sem_teste_gera_alertas(self):
        t = self._titulos()
        self.assertIn('Sem cópia recente — Banco', t)
        self.assertIn('Teste de restauração nunca realizado', t)

    def test_falha_na_ultima_execucao_alerta(self):
        self._exec('SUCESSO', horas_atras=5)
        self._exec('FALHA', horas_atras=1, mensagem='destino fora do ar')
        t = self._titulos()
        self.assertIn('Falha no último backup — Banco', t)
        self.assertNotIn('Sem cópia recente — Banco', t)

    def test_copia_antiga_alerta_atraso(self):
        self._exec('SUCESSO', horas_atras=30)
        self.assertIn('Sem cópia recente — Banco', self._titulos())

    def test_teste_vencido_e_em_dia(self):
        e = self._exec()
        BackupTesteRestauracao.objects.create(execucao=e, data=timezone.localdate() - timedelta(days=31),
                                              resultado='OK', tempo_minutos=30)
        self.assertIn('Teste mensal de restauração vencido', self._titulos())
        BackupTesteRestauracao.objects.create(execucao=e, data=timezone.localdate(), resultado='OK', tempo_minutos=30)
        self.assertEqual(self._titulos(), [])

    def test_painel_e_abas_abrem(self):
        self._exec(arquivo='banco.sql.gz.enc')
        for nome in ('backup_painel', 'backup_historico', 'backup_restauracao', 'backup_configuracao'):
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 200, nome)
        self.assertContains(self.client.get(reverse('backup_historico')), 'banco.sql.gz.enc')

    def test_funcionario_sem_acesso(self):
        self.client.force_login(self.func)
        r = self.client.get(reverse('backup_painel'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(reverse('sem_acesso')))

    def test_executar_agora_registra_execucao_manual(self):
        self.client.post(reverse('backup_executar', args=[self.rotina.pk]))
        e = BackupExecucao.objects.get()
        self.assertTrue(e.manual)
        self.assertEqual(e.status, 'SUCESSO')
        self.assertEqual(e.expira_em, timezone.localdate() + timedelta(days=30))
        self.assertEqual(len(e.hash_sha256), 64)

    def test_nao_executa_rotina_de_outra_empresa(self):
        d = BackupDestino.objects.create(empresa=self.outra, nome='X', endereco='s3://y')
        r2 = BackupRotina.objects.create(empresa=self.outra, destino=d, nome='Outra', origem='BANCO', horario=time(1, 0))
        self.assertEqual(self.client.post(reverse('backup_executar', args=[r2.pk])).status_code, 404)
        self.assertFalse(BackupExecucao.objects.exists())

    def test_registrar_teste_de_restauracao(self):
        e = self._exec()
        hoje = timezone.localdate()
        self.client.post(reverse('backup_restauracao'), {'execucao': e.pk, 'data': hoje.isoformat(), 'resultado': 'OK',
                                                         'tempo_minutos': 40, 'observacao': 'conferido'})
        t = BackupTesteRestauracao.objects.get()
        self.assertEqual((t.execucao, t.responsavel, t.tempo_minutos), (e, self.admin, 40))

    def test_teste_com_data_futura_e_recusado(self):
        e = self._exec()
        amanha = timezone.localdate() + timedelta(days=1)
        self.client.post(reverse('backup_restauracao'), {'execucao': e.pk, 'data': amanha.isoformat(), 'resultado': 'OK', 'tempo_minutos': 5})
        self.assertFalse(BackupTesteRestauracao.objects.exists())

    def test_configuracao_limita_retencao_e_muda_horario(self):
        self.client.post(reverse('backup_configuracao'), {'acao': 'destino', 'nome': 'Nuvem', 'tipo': 'SFTP',
                                                          'endereco': 'sftp://z', 'retencao_dias': '2', 'ativo': 'on'})
        self.destino.refresh_from_db()
        self.assertEqual((self.destino.tipo, self.destino.retencao_dias), ('SFTP', 7))
        self.client.post(reverse('backup_configuracao'), {'acao': 'rotina', 'rotina_id': self.rotina.pk, 'horario': '04:30'})
        self.rotina.refresh_from_db()
        self.assertEqual((self.rotina.horario, self.rotina.ativa), (time(4, 30), False))

    def test_tamanho_legivel(self):
        self.assertEqual(BackupExecucao(tamanho_bytes=int(1.5 * 1024 ** 3)).tamanho_legivel, '1,5 GB')
