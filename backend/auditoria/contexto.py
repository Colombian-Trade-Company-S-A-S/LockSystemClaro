"""Quién actúa y desde dónde: el contexto que acompaña a cada evento.

Se resuelve UNA vez, en la vista, que es donde existe la request, y desde ahí
viaja como un valor más. Los trabajos en segundo plano lo reciben como
argumento explícito: cuando el hilo corre la request ya no existe, y buscarla
dentro del worker es justo como se perdían el autor y la IP (hallazgos H-09 y
H-10).

Las tablas de operación (SyncJob, BulkSyncJob, PinCodeUsado, CambioTelevisor)
también se llenan desde aquí, con `usuario_id`, `api_key_id` e `ip`, para que
la bitácora central y las tablas de cada pantalla cuenten la misma historia.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from common.net import client_ip

from .catalogo import ActorTipo

NAVEGADOR_MAX = 300


def nombre_api_key(api_key) -> str:
    """'Integrador X (a1b2c3d4)': el nombre para leer, el prefijo para no
    confundir dos claves con el mismo nombre."""
    return f'{api_key.nombre} ({api_key.prefijo})'


@dataclass(frozen=True)
class Contexto:
    actor_tipo: str
    # Congelado en texto: si el usuario se borra o la clave se renombra, el
    # evento sigue diciendo quién fue.
    actor_nombre: str = ''
    usuario_id: Any = None
    api_key_id: Any = None
    ip: str | None = None
    navegador: str = ''

    @classmethod
    def de_request(cls, request) -> Contexto:
        """Contexto de quien hace la petición: usuario del panel, API-key o anónimo.

        Sirve igual para una request de DRF que para una de Django (el admin):
        las dos exponen `user` y `META`.
        """
        ip = client_ip(request)
        navegador = (request.META.get('HTTP_USER_AGENT') or '')[:NAVEGADOR_MAX]
        user = getattr(request, 'user', None)

        # El usuario sintético de una API-key lleva la clave colgada (ver
        # integracion/authentication.py). Se mira por atributo para no importar
        # la app de integración desde aquí.
        api_key = getattr(user, 'api_key', None)
        if api_key is not None:
            return cls(
                ActorTipo.API_KEY,
                nombre_api_key(api_key),
                api_key_id=api_key.pk,
                ip=ip,
                navegador=navegador,
            )
        if user is not None and user.is_authenticated and getattr(user, 'pk', None) is not None:
            return cls(
                ActorTipo.USUARIO,
                user.email,
                usuario_id=user.pk,
                ip=ip,
                navegador=navegador,
            )
        return cls(ActorTipo.ANONIMO, '', ip=ip, navegador=navegador)

    @classmethod
    def anonimo(cls, request, nombre: str = '') -> Contexto:
        """Alguien sin identidad comprobada. `nombre` es lo que dijo ser (el
        correo tecleado en un login fallido), guardado tal cual."""
        base = cls.de_request(request)
        return replace(
            base,
            actor_tipo=ActorTipo.ANONIMO,
            actor_nombre=(nombre or '')[:255],
            usuario_id=None,
            api_key_id=None,
        )

    @classmethod
    def de_usuario(cls, user, request=None) -> Contexto:
        """Un usuario concreto, aunque la petición aún no esté autenticada con
        JWT: el login que acaba de validarse, o el titular de un enlace de
        recuperación."""
        ip = client_ip(request) if request is not None else None
        navegador = (
            (request.META.get('HTTP_USER_AGENT') or '')[:NAVEGADOR_MAX]
            if request is not None
            else ''
        )
        return cls(
            ActorTipo.USUARIO, user.email, usuario_id=user.pk, ip=ip, navegador=navegador
        )

    @classmethod
    def sistema(cls) -> Contexto:
        return cls(ActorTipo.SISTEMA, 'Sistema')
