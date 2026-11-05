"""Huella de toda salida de información a Excel (hallazgo H-07) y de cada
acción denegada por permisos.

Un solo envoltorio para todas las rutas de exportación, presentes y futuras:
todas arman su archivo con `televisores.api.exports._respuesta_xlsx` o
`reportes_builder._respuesta_csv`, que marcan la respuesta con el número de
filas (`filas_exportadas`). Aquí, ya con la
respuesta en la mano, se registra quién descargó qué, con qué filtros y
cuántas filas. El conteo es lo que distingue una consulta puntual de una
descarga masiva.

También se registran los intentos DENEGADOS (403): contra una ruta de
exportación, como una exportación denegada; contra cualquier otra, como
`acceso_denegado`. Es alguien identificado intentando algo que su rol no
permite.

Va como middleware y no dentro de cada vista porque DRF autentica dentro de la
vista: solo al volver de ella `request.user` ya es el usuario del JWT o el de
la API-key (DRF lo copia a la request de Django).
"""
from __future__ import annotations

import re

from .catalogo import ActorTipo, Resultado
from .contexto import Contexto
from .services import registrar

# Toda ruta de exportación de la app lleva "export" en la URL
# (exportar-pincodes, dashboard/export/..., cambios/exportar/...).
RUTA_EXPORTACION = re.compile(r'/export')

_NOMBRE_ARCHIVO = re.compile(r'filename="?([^";]+)"?')


def _archivo(response) -> str:
    coincidencia = _NOMBRE_ARCHIVO.search(response.get('Content-Disposition', ''))
    return coincidencia.group(1) if coincidencia else ''


def _tipo(request) -> str:
    """Identificador estable de QUÉ se exportó: el nombre de la ruta, o el de
    la vista si la ruta no tiene nombre (las del dashboard)."""
    match = getattr(request, 'resolver_match', None)
    if match is None:
        return request.path
    return match.url_name or match.view_name.rsplit('.', 1)[-1] or request.path


def _filtros(request) -> dict:
    return {clave: request.GET.get(clave) for clave in request.GET}


def _parametros(request) -> dict:
    match = getattr(request, 'resolver_match', None)
    return dict(match.kwargs) if match is not None else {}


class AuditoriaExportacionesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        filas = getattr(response, 'filas_exportadas', None)
        if filas is not None and 200 <= response.status_code < 300:
            archivo = _archivo(response)
            # Sin try/except a propósito: si la huella no se puede escribir, el
            # archivo no sale. Una descarga sin registro es justo lo que se
            # quiere evitar.
            registrar(
                'exportacion',
                contexto=Contexto.de_request(request),
                objeto_tipo='exportacion',
                objeto_etiqueta=archivo,
                tipo=_tipo(request),
                ruta=request.path,
                archivo=archivo,
                filtros=_filtros(request),
                parametros=_parametros(request),
                filas=filas,
            )
        elif response.status_code == 403:
            contexto = Contexto.de_request(request)
            # Un anónimo no llega al 403 (recibe 401); y si llegara, no hay a
            # quién atribuirlo.
            if contexto.actor_tipo != ActorTipo.ANONIMO:
                es_exportacion = bool(RUTA_EXPORTACION.search(request.path))
                registrar(
                    'exportacion' if es_exportacion else 'acceso_denegado',
                    contexto=contexto,
                    resultado=Resultado.DENEGADO,
                    objeto_tipo='exportacion' if es_exportacion else '',
                    tipo=_tipo(request),
                    ruta=request.path,
                    metodo=request.method,
                    filtros=_filtros(request) or None,
                    parametros=_parametros(request) or None,
                )
        return response
