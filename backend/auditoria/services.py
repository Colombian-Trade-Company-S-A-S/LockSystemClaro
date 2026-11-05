"""Registro en la bitácora central: la función única por la que pasa todo evento.

Mismo patrón que ya funcionaba en el historial de cambios de televisores
(televisores/cambios.py): un solo punto de entrada, y cada vía de la app lo
invoca en vez de escribir filas a mano.

Reglas:
- La acción tiene que estar en el catálogo (catalogo.py); la categoría sale de
  ahí.
- Si el dato se escribe en una transacción, el evento va DENTRO de ella: si la
  escritura se revierte, la bitácora no puede afirmar algo que no ocurrió.
- Nunca entran contraseñas, claves de API ni Códigos Pin. Quien registra decide
  qué va en el detalle; aquí no se filtra nada a ciegas.
"""
from __future__ import annotations

import json
from collections.abc import Iterable

from django.core.serializers.json import DjangoJSONEncoder

from .catalogo import Resultado, categoria_de
from .contexto import Contexto, nombre_api_key
from .models import Evento


def _sin_nul(valor):
    """Quita el carácter NUL de todo texto. Postgres no lo admite ni en text ni
    en jsonb, y aquí llega texto que escribe el cliente (filtros de una URL, un
    correo): sin esto, cualquiera convertiría su petición en un 500 y no quedaría
    huella."""
    if isinstance(valor, str):
        return valor.replace('\x00', '')
    if isinstance(valor, dict):
        return {_sin_nul(k): _sin_nul(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_sin_nul(v) for v in valor]
    return valor


def _json(valor):
    """Normaliza a tipos JSON (fechas, UUID, decimales -> texto). Así el
    detalle en memoria es idéntico a lo que se lee después de la base."""
    return _sin_nul(json.loads(json.dumps(valor, cls=DjangoJSONEncoder)))


def etiqueta_televisor(tv) -> str:
    """'SERIAL · MAC', o solo la MAC si no tiene serial."""
    if tv.serial_number:
        return f'{tv.serial_number} · {tv.mac_address}'
    return tv.mac_address


def describir(obj) -> tuple[str, str, str]:
    """(tipo, id, etiqueta) de un objeto del dominio."""
    modelo = obj._meta.label_lower
    if modelo == 'televisores.televisor':
        return 'televisor', str(obj.pk), etiqueta_televisor(obj)
    if modelo == 'users.user':
        return 'usuario', str(obj.pk), obj.email
    if modelo == 'integracion.apikey':
        return 'api_key', str(obj.pk), nombre_api_key(obj)
    if modelo == 'televisores.bulksyncjob':
        tipo = 'validación' if obj.modo == obj.VALIDACION else 'sincronización'
        return 'lote', str(obj.pk), f'Lote #{obj.pk} ({tipo})'
    raise ValueError(f'No sé describir un {modelo} para la auditoría.')


def foto(obj, campos: Iterable[str]) -> dict:
    """Valores actuales de `campos`, listos para el detalle. Tomar ANTES de
    modificar o borrar: después ya no hay forma de saber qué había."""
    return _json({campo: getattr(obj, campo) for campo in campos})


def diferencias(antes: dict, despues: dict) -> tuple[dict, dict]:
    """Solo lo que cambió, como (antes, después)."""
    claves = [k for k in despues if antes.get(k) != despues.get(k)]
    return {k: antes.get(k) for k in claves}, {k: despues.get(k) for k in claves}


def construir(
    accion: str,
    *,
    contexto: Contexto | None = None,
    resultado: str = Resultado.EXITO,
    objeto=None,
    objeto_tipo: str = '',
    objeto_id='',
    objeto_etiqueta: str = '',
    antes: dict | None = None,
    despues: dict | None = None,
    **detalle,
) -> Evento:
    """Arma el evento SIN guardarlo (para registrar muchos de una vez)."""
    categoria = categoria_de(accion)
    ctx = contexto or Contexto.sistema()
    if objeto is not None:
        objeto_tipo, objeto_id, objeto_etiqueta = describir(objeto)

    datos = {clave: valor for clave, valor in detalle.items() if valor is not None}
    if antes is not None:
        datos['antes'] = antes
    if despues is not None:
        datos['despues'] = despues

    return Evento(
        categoria=categoria,
        accion=accion,
        resultado=resultado,
        actor_tipo=ctx.actor_tipo,
        usuario_id=ctx.usuario_id,
        api_key_id=ctx.api_key_id,
        actor_nombre=_sin_nul(ctx.actor_nombre or '')[:255],
        ip=ctx.ip or None,
        navegador=_sin_nul(ctx.navegador or '')[:300],
        objeto_tipo=objeto_tipo,
        objeto_id=_sin_nul(str(objeto_id or '')),
        objeto_etiqueta=_sin_nul(objeto_etiqueta or '')[:255],
        detalle=_json(datos),
    )


def registrar(accion: str, **kwargs) -> Evento:
    """Escribe un evento en la bitácora. Ver `construir` para los parámetros."""
    evento = construir(accion, **kwargs)
    evento.save()
    return evento


def registrar_lote(eventos: Iterable[Evento]) -> int:
    """Escribe varios eventos con una sola sentencia por cada 500.

    Para las vías masivas: importar mil televisores son mil eventos, y uno a
    uno serían mil round-trips contra la base remota.
    """
    lista = list(eventos)
    if lista:
        Evento.objects.bulk_create(lista, batch_size=500)
    return len(lista)
