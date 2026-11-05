"""
URL configuration for core project.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),

    # API de dominio
    path('api/', include('api.urls')),
    path('api/', include('televisores.api.urls')),
    path('api/', include('televisores.api.dashboard_urls')),

    # API de integración (por serial + API-key), aislada del panel.
    path('api/integracion/', include('televisores.api.integracion_urls')),
    # Gestión de API-keys desde el panel (solo Administrador).
    path('api/integracion/', include('integracion.api.urls')),

    # Usuarios y autenticación (register, token, refresh, verify, me)
    path('api/', include('users.api.urls')),

    path('api/auditoria/', include('auditoria.api.urls')),
]
