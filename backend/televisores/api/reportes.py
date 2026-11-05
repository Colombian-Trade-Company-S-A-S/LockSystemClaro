"""Resúmenes agregados para el Dashboard (JSON para los gráficos del front).

Un único endpoint (`GET /api/dashboard/resumen/`) devuelve todo lo que necesitan
los gráficos de la pantalla, más una serie temporal parametrizable por período.
Los reportes a nivel de registro (histórico por serial, acciones por usuario,
auditoría de pines) se descargan como Excel desde `reportes_export.py`.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from televisores.models import BulkSyncItem, BulkSyncJob, PinCodeUsado, SyncJob, Televisor

User = get_user_model()

ESTADOS_FILTRO = ('habilitado', 'inhabilitado')


def _parse_fecha(valor: str):
    try:
        return datetime.date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


@dataclass
class Filtros:
    """Filtros globales del dashboard, compartidos por el resumen y todas las
    exportaciones: rango de fechas, estado actual del televisor y serial."""

    desde: datetime.date | None = None
    hasta: datetime.date | None = None
    estado: str = ''  # '', 'habilitado' o 'inhabilitado'
    serial: str = ''

    @classmethod
    def from_request(cls, params) -> 'Filtros':
        estado = params.get('estado', '')
        return cls(
            desde=_parse_fecha(params.get('desde', '')),
            hasta=_parse_fecha(params.get('hasta', '')),
            estado=estado if estado in ESTADOS_FILTRO else '',
            serial=(params.get('serial') or '').strip(),
        )

    @property
    def activo(self) -> bool:
        return bool(self.desde or self.hasta or self.estado or self.serial)


def televisores_filtrados(f: Filtros | None = None):
    """Televisores acotados por fecha de registro, serial y estado actual (el
    estado es el vigente: no tiene fecha de corte, sólo el registro la tiene)."""
    f = f or Filtros()
    qs = Televisor.objects.all()
    if f.desde:
        qs = qs.filter(created_at__date__gte=f.desde)
    if f.hasta:
        qs = qs.filter(created_at__date__lte=f.hasta)
    if f.serial:
        qs = qs.filter(serial_number__icontains=f.serial)
    if f.estado == 'inhabilitado':
        qs = qs.filter(inhabilitado=True)
    elif f.estado == 'habilitado':
        qs = qs.filter(inhabilitado=False)
    return qs


def pines_filtrados(f: Filtros | None = None):
    """Pines usados acotados por fecha y serial del televisor asociado."""
    f = f or Filtros()
    qs = PinCodeUsado.objects.all()
    if f.desde:
        qs = qs.filter(creado__date__gte=f.desde)
    if f.hasta:
        qs = qs.filter(creado__date__lte=f.hasta)
    if f.serial:
        qs = qs.filter(televisor__serial_number__icontains=f.serial)
    if f.estado == 'inhabilitado':
        qs = qs.filter(televisor__inhabilitado=True)
    elif f.estado == 'habilitado':
        qs = qs.filter(televisor__inhabilitado=False)
    return qs


def acciones_querysets(f: Filtros | None = None):
    """Querysets de acciones (individuales + masivas) ya filtrados. Reutilizado
    por el resumen y por las exportaciones a nivel de registro."""
    f = f or Filtros()
    syncs = SyncJob.objects.select_related('televisor', 'usuario', 'api_key')
    items = (
        BulkSyncItem.objects
        .select_related('televisor', 'job', 'job__usuario', 'job__api_key')
        .filter(job__modo=BulkSyncJob.SYNC)
    )
    if f.desde:
        syncs = syncs.filter(creado__date__gte=f.desde)
        items = items.filter(job__creado__date__gte=f.desde)
    if f.hasta:
        syncs = syncs.filter(creado__date__lte=f.hasta)
        items = items.filter(job__creado__date__lte=f.hasta)
    if f.serial:
        # El de un televisor ya borrado vive en la copia del propio job (H-05).
        syncs = syncs.filter(
            Q(televisor__serial_number__icontains=f.serial)
            | Q(televisor__isnull=True, serial_number__icontains=f.serial)
        )
        items = items.filter(televisor__serial_number__icontains=f.serial)
    if f.estado == 'inhabilitado':
        syncs = syncs.filter(televisor__inhabilitado=True)
        items = items.filter(televisor__inhabilitado=True)
    elif f.estado == 'habilitado':
        syncs = syncs.filter(televisor__inhabilitado=False)
        items = items.filter(televisor__inhabilitado=False)
    return syncs, items


def _resultado_syncjob(estado: str) -> str:
    if estado == SyncJob.TERMINADO:
        return 'aplicada'
    if estado == SyncJob.ERROR:
        return 'error'
    return 'en_proceso'


def _resultado_item(estado: str) -> str:
    if estado == BulkSyncItem.OK:
        return 'aplicada'
    if estado == BulkSyncItem.ERROR:
        return 'error'
    return 'en_proceso'


def acciones(f: Filtros | None = None) -> list[dict]:
    """Todas las acciones de cambio de estado (individuales + masivas) como
    dicts homogéneos: {fecha, inhabilitar, resultado, mac, serial}."""
    syncs, items = acciones_querysets(f)
    filas: list[dict] = []
    for j in syncs:
        filas.append({
            'fecha': j.creado,
            'inhabilitar': j.inhabilitar,
            'resultado': _resultado_syncjob(j.estado),
            'mac': j.televisor.mac_address if j.televisor else (j.mac_address or '—'),
            'serial': j.televisor.serial_number if j.televisor else j.serial_number,
        })
    for it in items:
        filas.append({
            'fecha': it.job.creado,
            'inhabilitar': it.inhabilitar,
            'resultado': _resultado_item(it.estado),
            'mac': it.mac_address,
            'serial': it.televisor.serial_number if it.televisor else '',
        })
    return filas


def _estatus_inhabilitacion(qs=None) -> dict:
    """Estatus de inhabilitación discriminando producto financiado
    (financiado = tiene número de crédito)."""
    if qs is None:
        qs = Televisor.objects.all()
    resultado = {
        'inhabilitado': {'financiado': 0, 'no_financiado': 0},
        'habilitado': {'financiado': 0, 'no_financiado': 0},
    }
    for tv in qs.only('inhabilitado', 'numero_credito'):
        estado = 'inhabilitado' if tv.inhabilitado else 'habilitado'
        clave = 'financiado' if (tv.numero_credito or '').strip() else 'no_financiado'
        resultado[estado][clave] += 1
    return resultado


def _efectividad(filas: list[dict]) -> dict:
    """Acción enviada vs efectiva, por tipo de acción."""
    base = {'enviadas': 0, 'efectivas': 0, 'en_proceso': 0, 'error': 0}
    res = {'inhabilitacion': dict(base), 'habilitacion': dict(base)}
    for f in filas:
        clave = 'inhabilitacion' if f['inhabilitar'] else 'habilitacion'
        res[clave]['enviadas'] += 1
        if f['resultado'] == 'aplicada':
            res[clave]['efectivas'] += 1
        elif f['resultado'] == 'en_proceso':
            res[clave]['en_proceso'] += 1
        else:
            res[clave]['error'] += 1
    return res


def _clave_periodo(fecha, periodo: str) -> str:
    f = timezone.localtime(fecha)
    if periodo == 'dia':
        return f.strftime('%Y-%m-%d')
    if periodo == 'semana':
        return f.strftime('%G-S%V')  # año ISO + semana ISO
    if periodo == 'anio':
        return f.strftime('%Y')
    return f.strftime('%Y-%m')  # mes (por defecto)


def serie_tiempo(filas: list[dict], periodo: str) -> list[dict]:
    """Inhabilitaciones vs habilitaciones agrupadas por período."""
    buckets: dict[str, dict] = defaultdict(
        lambda: {'inhabilitaciones': 0, 'habilitaciones': 0}
    )
    for f in filas:
        clave = _clave_periodo(f['fecha'], periodo)
        if f['inhabilitar']:
            buckets[clave]['inhabilitaciones'] += 1
        else:
            buckets[clave]['habilitaciones'] += 1
    return [
        {'periodo': k, **buckets[k]} for k in sorted(buckets)
    ]


def _actividad_por_equipo(filas: list[dict]) -> list[dict]:
    """Dispersión: nº de inhabilitaciones vs habilitaciones por serial/MAC."""
    por_equipo: dict[str, dict] = {}
    for f in filas:
        clave = f['serial'] or f['mac']
        d = por_equipo.setdefault(
            clave,
            {'serial': f['serial'], 'mac': f['mac'],
             'inhabilitaciones': 0, 'habilitaciones': 0},
        )
        if f['inhabilitar']:
            d['inhabilitaciones'] += 1
        else:
            d['habilitaciones'] += 1
    for d in por_equipo.values():
        d['total'] = d['inhabilitaciones'] + d['habilitaciones']
    return sorted(por_equipo.values(), key=lambda d: d['total'], reverse=True)


def _usuarios() -> dict:
    total = User.objects.count()
    activos = User.objects.filter(is_active=True).count()
    staff = User.objects.filter(is_staff=True).count()
    return {
        'total': total,
        'activos': activos,
        'inactivos': total - activos,
        'staff': staff,
    }


class DashboardResumenView(APIView):
    """Todos los agregados que consumen los gráficos del dashboard."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        periodo = request.query_params.get('periodo', 'mes')
        if periodo not in ('dia', 'semana', 'mes', 'anio'):
            periodo = 'mes'

        f = Filtros.from_request(request.query_params)
        tv_qs = televisores_filtrados(f)

        filas = acciones(f)
        estatus = _estatus_inhabilitacion(tv_qs)
        total_tv = tv_qs.count()
        inhabilitados = tv_qs.filter(inhabilitado=True).count()
        financiados = (
            estatus['inhabilitado']['financiado']
            + estatus['habilitado']['financiado']
        )

        return Response({
            'kpis': {
                'televisores': total_tv,
                'inhabilitados': inhabilitados,
                'habilitados': total_tv - inhabilitados,
                'financiados': financiados,
                'pines_entregados': pines_filtrados(f).count(),
            },
            'estatus_inhabilitacion': estatus,
            'efectividad': _efectividad(filas),
            'serie_tiempo': {
                'periodo': periodo,
                'datos': serie_tiempo(filas, periodo),
            },
            'actividad_por_equipo': _actividad_por_equipo(filas),
            'usuarios': _usuarios(),
        })
