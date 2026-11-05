"""Autenticación por API-key para la API de integración (máquina-a-máquina).

Un integrador manda `Authorization: Api-Key <prefijo>.<secreto>`. Se valida la
clave y se devuelve un "usuario" sintético con permiso de operar televisores.

Ese usuario NO es una fila de la base: es un portador de permisos para que la
lógica existente de televisores (`CanOperate`, acciones de estado, pines…)
funcione sin cambios. Por eso su `pk` es None: nunca debe guardarse como llave
foránea de auditoría (ver `usuario_para_auditoria` en las vistas). El registro
de quién actuó, para las acciones por API-key, queda con usuario vacío + la IP.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import SimpleRateThrottle

from common.net import client_ip

from .models import ApiKey

KEYWORD = 'Api-Key'


class ApiKeyUser:
    """Identidad sintética de un integrador: puede operar televisores (estados,
    pines…), pero NO es administrador."""

    is_authenticated = True
    is_active = True
    is_superuser = False
    is_staff = False
    is_anonymous = False
    pk = None  # nunca es una fila real: no puede usarse como FK de auditoría

    def __init__(self, api_key: ApiKey):
        self.api_key = api_key

    @property
    def is_admin_role(self) -> bool:
        return False

    @property
    def can_operate(self) -> bool:
        # Un integrador SÍ opera sobre los televisores (estados, pines, masivos…).
        return True

    def __str__(self) -> str:
        return f'api-key<{self.api_key.prefijo}>'


class ApiKeyAuthentication(BaseAuthentication):
    """`Authorization: Api-Key <prefijo>.<secreto>`."""

    keyword = KEYWORD

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None  # no es una petición con API-key; deja pasar a otras auths

        if len(header) == 1:
            raise AuthenticationFailed('Falta la clave después de "Api-Key".')
        if len(header) > 2:
            raise AuthenticationFailed('El encabezado Api-Key no debe tener espacios.')

        clave = header[1].decode(HTTP_HEADER_ENCODING)
        prefijo = clave.split('.')[0]

        # Un solo mensaje para clave inexistente o incorrecta: no se revela si el
        # prefijo existe (evita enumerar prefijos válidos).
        invalida = AuthenticationFailed('API key inválida o revocada.')
        try:
            api_key = ApiKey.objects.get(prefijo=prefijo, activa=True)
        except ApiKey.DoesNotExist:
            raise invalida
        if not api_key.coincide(clave):
            raise invalida
        if api_key.expirada:
            raise AuthenticationFailed('Esta API key expiró.')
        # Misma IP que queda en la auditoría: leída desde la derecha de
        # X-Forwarded-For, que el cliente no puede falsificar.
        if not api_key.ip_permitida(client_ip(request)):
            # No se dice "IP no permitida" para no confirmar que la clave es
            # válida a quien la usa desde una IP no autorizada.
            raise invalida

        self._marcar_uso(api_key)
        return (ApiKeyUser(api_key), api_key)

    def authenticate_header(self, request):
        # Hace que un 401 responda con WWW-Authenticate: Api-Key.
        return self.keyword

    @staticmethod
    def _marcar_uso(api_key: ApiKey) -> None:
        """Actualiza `ultimo_uso` como mucho una vez por minuto: sirve para ver
        actividad sin escribir en cada petición."""
        ahora = timezone.now()
        if api_key.ultimo_uso is None or (ahora - api_key.ultimo_uso).total_seconds() > 60:
            ApiKey.objects.filter(pk=api_key.pk).update(ultimo_uso=ahora)


class ApiKeyRateThrottle(SimpleRateThrottle):
    """Límite de tasa por API-key (no por IP ni por usuario).

    Sin esto, todas las peticiones por API-key compartirían el mismo cubo (el
    usuario sintético no tiene pk), y un integrador ruidoso frenaría a los demás.
    """

    scope = 'integracion'

    def get_cache_key(self, request, view):
        if not isinstance(getattr(request, 'auth', None), ApiKey):
            return None  # no aplica a peticiones que no son por API-key
        return self.cache_format % {'scope': self.scope, 'ident': request.auth.pk}
