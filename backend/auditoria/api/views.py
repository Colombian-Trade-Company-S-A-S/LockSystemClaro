"""Consulta de la bitácora central (pantalla «Auditoría»).

Solo lectura y solo el Administrador (decisión D-4 del plan de trazabilidad:
mientras no se defina otra cosa, la auditoría la ve quien gobierna permisos).
La exportación pasa por `_respuesta_xlsx`, así que también deja su huella:
quien descarga la bitácora queda en la bitácora.
"""
from __future__ import annotations

import ipaddress
import json

from django.db.models import Q
from django.utils import timezone
from openpyxl import Workbook
from rest_framework import permissions
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from auditoria.catalogo import ACCIONES, ActorTipo, Categoria, Resultado
from auditoria.models import Evento
from televisores.api.exports import _estilar_encabezado, _respuesta_xlsx
from televisores.api.filtros import filtrar_por_fecha
from users.permissions import IsAdminRole

from .serializers import EventoSerializer

# Tope del Excel. La bitácora crece sin parar; sin límite, un rango mal elegido
# sería una descarga de cientos de miles de filas. Si se llega, el archivo lo
# avisa en su última fila.
MAX_FILAS_EXPORTACION = 50_000


def _texto(params, clave: str) -> str:
    """Valor de un filtro, sin el NUL que Postgres rechazaría en la consulta."""
    return (params.get(clave) or '').replace('\x00', '').strip()


def filtrar_eventos(params) -> 'QuerySet[Evento]':
    """Filtros compartidos por la tabla y su Excel: el archivo trae exactamente
    lo que se ve en pantalla.

    - desde / hasta: rango de fechas inclusivo (AAAA-MM-DD, hora de Bogotá).
    - categoria, accion, resultado, actor_tipo: valores exactos del catálogo.
    - actor: texto dentro del nombre del actor (correo o nombre de la API key).
    - objeto_tipo + objeto_id: un objeto concreto («todo lo que pasó con este
      televisor»).
    - objeto: texto dentro de la etiqueta del objeto (serial, MAC, correo...).
    - ip: IP exacta.
    """
    qs = filtrar_por_fecha(
        Evento.objects.all(), params.get('desde'), params.get('hasta'), campo='momento'
    )
    for campo in ('categoria', 'accion', 'resultado', 'actor_tipo', 'objeto_tipo', 'objeto_id'):
        valor = _texto(params, campo)
        if valor:
            qs = qs.filter(**{campo: valor})
    actor = _texto(params, 'actor')
    if actor:
        qs = qs.filter(actor_nombre__icontains=actor)
    objeto = _texto(params, 'objeto')
    if objeto:
        qs = qs.filter(Q(objeto_etiqueta__icontains=objeto) | Q(objeto_id=objeto))
    ip = _texto(params, 'ip')
    if ip:
        # La columna es inet: comparar con algo que no es una IP es un error en
        # Postgres, no un "sin resultados".
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return qs.none()
        qs = qs.filter(ip=ip)
    return qs


class EventosPaginacion(PageNumberPagination):
    page_size = 25


class EventoListView(ListAPIView):
    """GET /api/auditoria/eventos/ — la bitácora, paginada y filtrada."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]
    serializer_class = EventoSerializer
    pagination_class = EventosPaginacion
    # Los filtros son los de `filtrar_eventos`; el buscador genérico de DRF no
    # aplica aquí.
    filter_backends: list = []

    def get_queryset(self):
        return filtrar_eventos(self.request.query_params)


class EventoExportView(APIView):
    """GET /api/auditoria/eventos/exportar/ — los mismos filtros, en Excel."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        qs = filtrar_eventos(request.query_params)
        wb = Workbook()
        ws = wb.active
        ws.title = 'Auditoría'
        ws.append([
            'Fecha', 'Categoría', 'Acción', 'Resultado', 'Actor', 'Tipo de actor',
            'IP', 'Navegador', 'Tipo de objeto', 'Objeto', 'Id del objeto', 'Detalle',
        ])
        _estilar_encabezado(ws)

        n = 0
        for e in qs[:MAX_FILAS_EXPORTACION].iterator(chunk_size=2000):
            n += 1
            ws.append([
                timezone.localtime(e.momento).strftime('%Y-%m-%d %H:%M:%S'),
                e.get_categoria_display(),
                e.accion_display,
                e.get_resultado_display(),
                e.actor_nombre,
                e.get_actor_tipo_display(),
                e.ip or '',
                e.navegador,
                e.objeto_tipo,
                e.objeto_etiqueta,
                e.objeto_id,
                json.dumps(e.detalle, ensure_ascii=False) if e.detalle else '',
            ])
        if n == MAX_FILAS_EXPORTACION:
            ws.append([f'Archivo truncado a {MAX_FILAS_EXPORTACION} filas: acota el rango de fechas.'])

        for col, ancho in zip('ABCDEFGHIJKL', (20, 22, 32, 11, 32, 12, 16, 30, 14, 34, 38, 60)):
            ws.column_dimensions[col].width = ancho

        desde = request.query_params.get('desde') or 'inicio'
        hasta = request.query_params.get('hasta') or 'hoy'
        return _respuesta_xlsx(wb, f'auditoria_{desde}_a_{hasta}.xlsx')


class CatalogoView(APIView):
    """GET /api/auditoria/catalogo/ — categorías, acciones y demás valores con
    su etiqueta, para armar los filtros sin duplicar el catálogo en el front."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        def opciones(choices):
            return [{'valor': valor, 'etiqueta': etiqueta} for valor, etiqueta in choices]

        return Response({
            'categorias': opciones(Categoria.choices),
            'acciones': [
                {'valor': accion, 'etiqueta': etiqueta, 'categoria': categoria}
                for accion, (categoria, etiqueta) in ACCIONES.items()
            ],
            'resultados': opciones(Resultado.choices),
            'actor_tipos': opciones(ActorTipo.choices),
        })
