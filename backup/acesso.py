from django.shortcuts import render


def get_empresa(request):
    perfil = getattr(request.user, 'perfil', None)
    return getattr(perfil, 'empresa', None)


def is_admin_empresa(user):
    return user.is_superuser or (hasattr(user, 'perfil') and user.perfil.tipo == 'ADMIN')


def sem_acesso(request):
    return render(request, 'backup/sem_acesso.html', status=403)
