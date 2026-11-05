"""Registro del historial de cambios en los datos de un televisor.

Punto único por el que pasan las tres vías de edición (formulario individual,
carga masiva y API de integración), para que ninguna se quede sin auditar y
todas comparen los valores con el mismo criterio.

Solo cubre datos identificatorios: MAC, serial y número de crédito. El estado
(habilitado/inhabilitado) tiene su propia bitácora — ver models.CambioTelevisor.
"""
from __future__ import annotations

from auditoria.contexto import Contexto
from auditoria.services import foto

from .models import CambioTelevisor, Televisor

# Campos auditados, en el orden en que se muestran.
CAMPOS_AUDITADOS = (
    CambioTelevisor.MAC,
    CambioTelevisor.SERIAL,
    CambioTelevisor.CREDITO,
)

# Todo lo que define a un televisor. Es lo que la bitácora central guarda en un
# alta o una baja: en la baja, es la única forma de saber después qué se perdió.
CAMPOS_FOTO = (
    'mac_address',
    'serial_number',
    'numero_credito',
    'eui64',
    'inhabilitado',
    'created_at',
)


def snapshot(televisor: Televisor) -> dict[str, str]:
    """Valores actuales de los campos auditados. Tomar ANTES de modificar."""
    return {campo: (getattr(televisor, campo, '') or '') for campo in CAMPOS_AUDITADOS}


def foto_completa(televisor: Televisor) -> dict:
    """Estado completo del televisor para la bitácora central."""
    return foto(televisor, CAMPOS_FOTO)


def _diferencias(antes: dict[str, str], televisor: Televisor) -> list[tuple[str, str, str]]:
    """(campo, valor_anterior, valor_nuevo) de lo que realmente cambió.

    Compara ya normalizado (sin espacios sobrantes) para no registrar cambios
    fantasma: guardar el formulario sin tocar nada, o un Excel con un espacio de
    más al final del serial, no son modificaciones que nadie quiera auditar.
    """
    cambios = []
    for campo in CAMPOS_AUDITADOS:
        anterior = (antes.get(campo) or '').strip()
        nuevo = (getattr(televisor, campo, '') or '').strip()
        if anterior != nuevo:
            cambios.append((campo, anterior, nuevo))
    return cambios


def _fila(televisor: Televisor, campo: str, anterior: str, nuevo: str,
          *, contexto: Contexto, origen) -> CambioTelevisor:
    return CambioTelevisor(
        televisor=televisor,
        # Identificadores ya actualizados: es como se busca el televisor hoy.
        mac_address=televisor.mac_address or '',
        serial_number=televisor.serial_number or '',
        numero_credito=televisor.numero_credito or '',
        campo=campo,
        valor_anterior=anterior[:120],
        valor_nuevo=nuevo[:120],
        origen=origen,
        # Por ids y no por objetos: el "usuario" de una API-key no es una fila
        # de la base y no puede ir en la FK de usuario. Esa acción queda con la
        # API-key en su propia columna (H-06).
        usuario_id=contexto.usuario_id,
        api_key_id=contexto.api_key_id,
        ip=contexto.ip,
    )


def registrar_cambios(
    *,
    televisor: Televisor,
    antes: dict[str, str],
    contexto: Contexto,
    origen: str = CambioTelevisor.INDIVIDUAL,
) -> list[CambioTelevisor]:
    """Guarda una fila por cada campo que cambió. Devuelve las filas creadas."""
    filas = [
        _fila(televisor, campo, anterior, nuevo, contexto=contexto, origen=origen)
        for campo, anterior, nuevo in _diferencias(antes, televisor)
    ]
    if filas:
        CambioTelevisor.objects.bulk_create(filas)
    return filas


def registrar_cambios_masivos(
    *,
    pares: list[tuple[Televisor, dict[str, str]]],
    contexto: Contexto,
) -> int:
    """Versión por lotes: recibe (televisor_ya_modificado, valores_previos).

    Una sola escritura para todo el archivo. Con un `bulk_create` por televisor,
    importar mil filas serían mil round-trips contra una base de datos remota —
    justo lo que el importador evita para los propios televisores.
    """
    filas: list[CambioTelevisor] = []
    for televisor, antes in pares:
        filas.extend(
            _fila(
                televisor, campo, anterior, nuevo,
                contexto=contexto, origen=CambioTelevisor.MASIVO,
            )
            for campo, anterior, nuevo in _diferencias(antes, televisor)
        )
    if filas:
        CambioTelevisor.objects.bulk_create(filas, batch_size=500)
    return len(filas)
