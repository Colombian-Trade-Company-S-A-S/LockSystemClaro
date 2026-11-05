"""IP real del cliente detrás del proxy de Render.

Es la ÚNICA función que decide desde qué IP llegó una petición. Todo lo que la
app guarda o compara por IP sale de aquí: las bitácoras (sincronizaciones,
pines, historial de cambios, recuperación de contraseña), la sesión activa y su
identidad de navegador, y la lista blanca de las API-keys.

Por qué no la primera entrada de X-Forwarded-For: esa cabecera la puede mandar
el propio cliente, y el balanceador solo AÑADE al final la IP de quien se le
conectó. Con `X-Forwarded-For: 1.2.3.4` cualquiera elegía la IP que quedaba en
la auditoría. Lo único fiable son las entradas que pusieron nuestros proxies,
así que se cuenta desde la derecha (hallazgo H-01 del diagnóstico de
trazabilidad).

Es el mismo criterio que usa DRF para el rate limiting (`NUM_PROXIES`, que en
settings apunta a la misma variable): la IP auditada y la IP limitada coinciden.
"""
from __future__ import annotations

import ipaddress

from django.conf import settings


def _ip_valida(valor: str | None) -> str | None:
    """`valor` si es una dirección IP; si no, None.

    Toda columna de IP es `inet` en Postgres: guardar otra cosa revienta la
    escritura y la petición entera termina en 500. No se cae a REMOTE_ADDR:
    esa sería la IP del proxy, y la auditoría la mostraría como la del cliente.
    Mejor un "no se sabe". La lista blanca de API-keys niega ante un None.
    """
    try:
        ipaddress.ip_address(valor or '')
    except ValueError:
        return None
    return valor


def client_ip(request) -> str | None:
    """IP del cliente, a prueba de X-Forwarded-For falsificado.

    Toma la entrada que añadió el proxy de confianza más externo
    (`PROXIES_DE_CONFIANZA` saltos desde la derecha). Con 0 proxies, o sin la
    cabecera, usa la dirección de la conexión (REMOTE_ADDR). None si lo que hay
    ahí no es una IP.
    """
    saltos = settings.PROXIES_DE_CONFIANZA
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if saltos and xff:
        partes = [p.strip() for p in xff.split(',') if p.strip()]
        if partes:
            # Si hay menos entradas que proxies, todas las puso un proxy nuestro:
            # la más a la izquierda es la del cliente.
            return _ip_valida(partes[-min(saltos, len(partes))])
    return _ip_valida(request.META.get('REMOTE_ADDR'))
