"""Rutas de la auditoría. Se montan bajo `/api/auditoria/` (ver core/urls.py)."""
from django.urls import path

from .views import CatalogoView, EventoExportView, EventoListView

urlpatterns = [
    path('eventos/', EventoListView.as_view(), name='auditoria-eventos'),
    path('eventos/exportar/', EventoExportView.as_view(), name='auditoria-eventos-exportar'),
    path('catalogo/', CatalogoView.as_view(), name='auditoria-catalogo'),
]
