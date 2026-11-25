"""Backup externo (protótipo — ACE II): painel, histórico, testes de restauração e configuração.

No protótipo a cópia em si não é feita: o botão "Executar agora" registra uma execução simulada.
Na versão final, um comando agendado (cron) faria o dump, a criptografia e o envio ao destino,
gravando o resultado em BackupExecucao do mesmo jeito.
"""
import hashlib
import secrets
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models_backup import BackupDestino, BackupExecucao, BackupRotina, BackupTesteRestauracao, prazo_teste
from .acesso import get_empresa, is_admin_empresa

JANELA_HORAS = 26   # rotina diária: sem cópia boa há mais que isso = atrasada


def backup_alertas(empresa, agora=None):
    """Lista de {nivel, titulo, texto} a partir do estado atual. Nível 'erro' ou 'aviso'."""
    agora = agora or timezone.now()
    alertas = []
    rotinas = list(BackupRotina.objects.filter(empresa=empresa, ativa=True).select_related('destino'))
    if not rotinas:
        alertas.append({'nivel': 'aviso', 'titulo': 'Nenhuma rotina ativa',
                        'texto': 'Nenhum dado está sendo copiado para fora da sede.'})
    for r in rotinas:
        ult, ok = r.ultima, r.ultima_ok
        if ult and ult.status == 'FALHA':
            alertas.append({'nivel': 'erro', 'titulo': f'Falha no último backup — {r.nome}',
                            'texto': f'{timezone.localtime(ult.inicio):%d/%m/%Y %H:%M}: {ult.mensagem or "sem detalhe"}'})
        if not ok or agora - ok.inicio > timedelta(hours=JANELA_HORAS):
            quando = f'desde {timezone.localtime(ok.inicio):%d/%m/%Y %H:%M}' if ok else 'nunca houve cópia concluída'
            alertas.append({'nivel': 'erro', 'titulo': f'Sem cópia recente — {r.nome}',
                            'texto': f'Última cópia concluída: {quando}.'})
        if not r.destino.ativo:
            alertas.append({'nivel': 'erro', 'titulo': f'Destino desativado — {r.nome}',
                            'texto': f'O destino "{r.destino.nome}" está desativado.'})
    ultimo_teste = BackupTesteRestauracao.objects.filter(execucao__rotina__empresa=empresa).first()
    vence = prazo_teste(ultimo_teste)
    hoje = timezone.localdate()
    if not ultimo_teste:
        alertas.append({'nivel': 'aviso', 'titulo': 'Teste de restauração nunca realizado',
                        'texto': 'Sem teste não há prova de que as cópias voltam.'})
    elif vence < hoje:
        alertas.append({'nivel': 'aviso', 'titulo': 'Teste mensal de restauração vencido',
                        'texto': f'Último teste em {ultimo_teste.data:%d/%m/%Y}; venceu em {vence:%d/%m/%Y}.'})
    elif ultimo_teste.resultado != 'OK':
        alertas.append({'nivel': 'aviso', 'titulo': 'Último teste de restauração com problema',
                        'texto': f'{ultimo_teste.data:%d/%m/%Y}: {ultimo_teste.get_resultado_display()}.'})
    return alertas


def _proxima(rotina, agora):
    local = timezone.localtime(agora)
    dia = local.date() if local.time() < rotina.horario else local.date() + timedelta(days=1)
    return datetime.combine(dia, rotina.horario)


@login_required
@user_passes_test(is_admin_empresa, login_url='sem_acesso')
def backup_painel(request):
    empresa = get_empresa(request)
    agora = timezone.now()
    hoje = timezone.localdate()
    dias = [hoje - timedelta(days=i) for i in range(13, -1, -1)]
    rotinas = []
    for r in BackupRotina.objects.filter(empresa=empresa).select_related('destino'):
        por_dia = {}
        for e in r.execucoes.filter(inicio__date__gte=dias[0] - timedelta(days=1)):
            d = timezone.localtime(e.inicio).date()
            # o pior resultado do dia prevalece (falha > andamento > sucesso)
            atual = por_dia.get(d)
            if not atual or (e.status == 'FALHA') or (atual == 'SUCESSO' and e.status == 'EM_ANDAMENTO'):
                por_dia[d] = e.status
        rotinas.append({'r': r, 'ultima': r.ultima, 'ultima_ok': r.ultima_ok, 'proxima': _proxima(r, agora),
                        'dias': [{'data': d, 'status': por_dia.get(d)} for d in dias]})
    execs = BackupExecucao.objects.filter(rotina__empresa=empresa)
    ultimos30 = execs.filter(inicio__gte=agora - timedelta(days=30))
    total30 = ultimos30.count()
    ok30 = ultimos30.filter(status='SUCESSO').count()
    guardadas = execs.filter(status='SUCESSO', expira_em__gte=hoje)
    ultimo_teste = BackupTesteRestauracao.objects.filter(execucao__rotina__empresa=empresa).select_related('execucao__rotina').first()
    return render(request, 'backup/backup_painel.html', {
        'alertas': backup_alertas(empresa, agora),
        'rotinas': rotinas,
        'dias': dias,
        'taxa30': round(100 * ok30 / total30) if total30 else None,
        'ok30': ok30, 'total30': total30,
        'copias': guardadas.count(),
        'espaco': BackupExecucao(tamanho_bytes=sum(guardadas.values_list('tamanho_bytes', flat=True))).tamanho_legivel,
        'ultimo_teste': ultimo_teste,
        'vence_teste': prazo_teste(ultimo_teste),
        'destino': BackupDestino.objects.filter(empresa=empresa, ativo=True).first(),
        'recentes': execs.select_related('rotina')[:6],
    })


@login_required
@user_passes_test(is_admin_empresa, login_url='sem_acesso')
@require_POST
def backup_executar(request, pk):
    """Protótipo: simula a cópia e registra a execução como seria gravada pela rotina real."""
    rotina = get_object_or_404(BackupRotina.objects.select_related('destino'), pk=pk, empresa=get_empresa(request))
    base = rotina.ultima_ok
    inicio = timezone.now()
    tamanho = int((base.tamanho_bytes if base else 250 * 1024 ** 2) * 1.002)
    ext = 'sql.gz.enc' if rotina.origem == 'BANCO' else 'tar.gz.enc'
    BackupExecucao.objects.create(
        rotina=rotina, inicio=inicio, fim=inicio + timedelta(minutes=3, seconds=12), status='SUCESSO', manual=True,
        arquivo=f'{rotina.origem.lower()}_{timezone.localtime(inicio):%Y%m%d_%H%M}.{ext}',
        tamanho_bytes=tamanho, hash_sha256=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        mensagem=f'Execução manual por {request.user.get_full_name() or request.user.username}.',
        expira_em=timezone.localdate() + timedelta(days=rotina.destino.retencao_dias))
    messages.success(request, f'Backup "{rotina.nome}" executado e enviado ao destino externo.')
    return redirect(request.POST.get('voltar') or 'backup_painel')


@login_required
@user_passes_test(is_admin_empresa, login_url='sem_acesso')
def backup_historico(request):
    empresa = get_empresa(request)
    qs = BackupExecucao.objects.filter(rotina__empresa=empresa).select_related('rotina')
    f = {k: request.GET.get(k, '') for k in ('rotina', 'status', 'de', 'ate')}
    if f['rotina'].isdigit():
        qs = qs.filter(rotina_id=int(f['rotina']))
    if f['status'] in dict(BackupExecucao.STATUS):
        qs = qs.filter(status=f['status'])
    if f['de']:
        qs = qs.filter(inicio__date__gte=f['de'])
    if f['ate']:
        qs = qs.filter(inicio__date__lte=f['ate'])
    pagina = Paginator(qs, 20).get_page(request.GET.get('page'))
    return render(request, 'backup/backup_historico.html', {
        'pagina': pagina, 'f': f, 'total': qs.count(), 'falhas': qs.filter(status='FALHA').count(),
        'rotinas': BackupRotina.objects.filter(empresa=empresa), 'status_opcoes': BackupExecucao.STATUS,
    })


@login_required
@user_passes_test(is_admin_empresa, login_url='sem_acesso')
def backup_restauracao(request):
    empresa = get_empresa(request)
    copias = BackupExecucao.objects.filter(rotina__empresa=empresa, status='SUCESSO').select_related('rotina')[:30]
    if request.method == 'POST':
        execucao = get_object_or_404(BackupExecucao, pk=request.POST.get('execucao'), rotina__empresa=empresa, status='SUCESSO')
        resultado = request.POST.get('resultado')
        try:
            tempo = int(request.POST.get('tempo_minutos') or 0)
            data = datetime.strptime(request.POST.get('data') or '', '%Y-%m-%d').date()
        except ValueError:
            tempo, data = 0, None
        if resultado not in dict(BackupTesteRestauracao.RESULTADOS) or tempo <= 0 or not data:
            messages.error(request, 'Preencha a cópia testada, a data, o resultado e o tempo.')
        elif data > timezone.localdate():
            messages.error(request, 'A data do teste não pode ser futura.')
        else:
            BackupTesteRestauracao.objects.create(execucao=execucao, data=data, responsavel=request.user, resultado=resultado,
                                                  tempo_minutos=tempo, observacao=(request.POST.get('observacao') or '').strip()[:2000])
            messages.success(request, 'Teste de restauração registrado.')
        return redirect('backup_restauracao')
    testes = BackupTesteRestauracao.objects.filter(execucao__rotina__empresa=empresa).select_related('execucao__rotina', 'responsavel')
    ultimo = testes.first()
    return render(request, 'backup/backup_restauracao.html', {
        'testes': testes[:24], 'copias': copias, 'ultimo': ultimo, 'vence': prazo_teste(ultimo),
        'hoje': timezone.localdate(), 'resultados': BackupTesteRestauracao.RESULTADOS,
    })


@login_required
@user_passes_test(is_admin_empresa, login_url='sem_acesso')
def backup_configuracao(request):
    empresa = get_empresa(request)
    destino = BackupDestino.objects.filter(empresa=empresa).first()
    if request.method == 'POST':
        acao = request.POST.get('acao')
        if acao == 'destino':
            destino = destino or BackupDestino(empresa=empresa)
            destino.nome = (request.POST.get('nome') or '').strip()[:80] or 'Destino externo'
            destino.tipo = request.POST.get('tipo') if request.POST.get('tipo') in dict(BackupDestino.TIPOS) else 'S3'
            destino.endereco = (request.POST.get('endereco') or '').strip()[:200]
            try:
                destino.retencao_dias = max(7, min(365, int(request.POST.get('retencao_dias') or 30)))
            except ValueError:
                destino.retencao_dias = 30
            destino.ativo = request.POST.get('ativo') == 'on'
            destino.save()
            messages.success(request, 'Destino externo salvo.')
        elif acao == 'rotina' and destino:
            rotina = get_object_or_404(BackupRotina, pk=request.POST.get('rotina_id'), empresa=empresa)
            try:
                rotina.horario = time.fromisoformat(request.POST.get('horario') or '')
            except ValueError:
                messages.error(request, 'Horário inválido.')
                return redirect('backup_configuracao')
            rotina.ativa = request.POST.get('ativa') == 'on'
            rotina.save(update_fields=['horario', 'ativa'])
            messages.success(request, f'Rotina "{rotina.nome}" atualizada.')
        return redirect('backup_configuracao')
    return render(request, 'backup/backup_configuracao.html', {
        'destino': destino, 'tipos': BackupDestino.TIPOS,
        'rotinas': BackupRotina.objects.filter(empresa=empresa).select_related('destino'),
    })
