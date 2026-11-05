"""Utilidades compartidas por las pruebas de la bitácora."""
from __future__ import annotations

import json

from auditoria.models import Evento

CLAVE = 'ClaveSegura123'
CHROME = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
EQUIPO = '190.10.20.30'


def eventos(accion: str):
    return Evento.objects.filter(accion=accion).order_by('id')


def ultimo(accion: str) -> Evento | None:
    return eventos(accion).last()


def todo_el_texto() -> str:
    """Todo lo que guarda la bitácora, como texto: para comprobar que un
    secreto (contraseña, clave, pin) no aparece en ninguna parte."""
    return json.dumps(
        list(Evento.objects.values('actor_nombre', 'objeto_etiqueta', 'detalle')),
        default=str,
        ensure_ascii=False,
    )
