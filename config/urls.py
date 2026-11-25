from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='backup_painel', permanent=False)),
    path('login/', auth_views.LoginView.as_view(template_name='backup/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('backup/', include('backup.urls')),
]
