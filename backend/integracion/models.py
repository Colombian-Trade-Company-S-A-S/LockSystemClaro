"""Credenciales de integración máquina-a-máquina (API-keys).

Este proyecto NO es multi-tenant: una API-key no pertenece a ninguna empresa,
simplemente autoriza a un integrador a operar la API de integración
(`/api/integracion/...`), donde cada televisor se direcciona por su serial.

Una clave se ve UNA sola vez, al crearla (se devuelve en claro en esa única
respuesta). Después solo queda su hash: si se pierde, se revoca y se genera otra.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import uuid

from django.db import models


def separar_ips(texto: str) -> list[str]:
    """Entradas de la lista blanca: una por línea o separadas por coma."""
    return [
        e.strip()
        for linea in (texto or '').splitlines()
        for e in linea.split(',')
        if e.strip()
    ]


def _hash_clave(clave: str) -> str:
    """SHA-256 de la clave. Basta porque la clave es un token aleatorio de alta
    entropía (no una contraseña elegida por humanos): no necesita hashing lento.
    Nunca se guarda la clave en claro; solo este hash."""
    return hashlib.sha256(clave.encode('utf-8')).hexdigest()


class ApiKey(models.Model):
    """Credencial de integración. Un integrador manda
    `Authorization: Api-Key <prefijo>.<secreto>` y con eso opera la API de
    integración. El serial dice *cuál* televisor; la API-key dice *si puede*.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    nombre = models.CharField(
        'nombre',
        max_length=100,
        help_text='Para identificar al integrador, p. ej. "ERP de Google".',
    )

    # Parte pública de la clave: identifica el registro sin revelar el secreto.
    # Se busca por aquí y luego se compara el hash del token completo.
    prefijo = models.CharField('prefijo', max_length=16, unique=True, editable=False)
    hash_clave = models.CharField('hash', max_length=64, editable=False)

    activa = models.BooleanField('activa', default=True)

    # --- Endurecimiento opcional (apagado por defecto: no cambia el uso) ---
    # Lista blanca de IPs/rangos (uno por línea o separados por coma). Vacío =
    # se acepta desde cualquier IP (comportamiento documentado por defecto). Si
    # se define, la clave SOLO funciona desde esas IPs, aunque sea válida.
    ips_permitidas = models.TextField(
        'IPs permitidas',
        blank=True,
        default='',
        help_text='IPs o rangos CIDR (uno por línea). Vacío = cualquier IP.',
    )
    # Caducidad opcional. Vacío = no expira (comportamiento por defecto).
    expira = models.DateTimeField('expira el', null=True, blank=True)

    creada = models.DateTimeField('fecha de creación', auto_now_add=True)
    ultimo_uso = models.DateTimeField('último uso', null=True, blank=True)

    class Meta:
        verbose_name = 'API key'
        verbose_name_plural = 'API keys'
        ordering = ['-creada']

    def __str__(self) -> str:
        return f'{self.nombre} ({self.prefijo}…)'

    @classmethod
    def generar(
        cls,
        *,
        nombre: str,
        ips_permitidas: str = '',
        expira=None,
    ) -> tuple['ApiKey', str]:
        """Crea una API-key y devuelve (registro, clave_en_claro).

        La clave en claro es lo ÚNICO que el llamador puede mostrar al usuario, y
        solo aquí: en la base queda su hash, no ella.
        """
        prefijo = secrets.token_hex(4)  # 8 caracteres hex
        secreto = secrets.token_urlsafe(32)
        clave = f'{prefijo}.{secreto}'
        obj = cls.objects.create(
            nombre=nombre.strip(),
            prefijo=prefijo,
            hash_clave=_hash_clave(clave),
            ips_permitidas=(ips_permitidas or '').strip(),
            expira=expira,
        )
        return obj, clave

    def coincide(self, clave: str) -> bool:
        """Comparación en tiempo constante (evita timing attacks sobre el hash)."""
        return hmac.compare_digest(self.hash_clave, _hash_clave(clave))

    @property
    def expirada(self) -> bool:
        from django.utils import timezone

        return self.expira is not None and timezone.now() >= self.expira

    def ip_permitida(self, ip: str | None) -> bool:
        """True si `ip` puede usar esta clave.

        Sin lista definida, cualquier IP vale (comportamiento documentado). Con
        lista, solo las IPs/rangos indicados. Las entradas mal escritas se
        ignoran (nunca abren el acceso por error)."""
        entradas = separar_ips(self.ips_permitidas)
        if not entradas:
            return True
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        for entrada in entradas:
            try:
                if addr in ipaddress.ip_network(entrada, strict=False):
                    return True
            except ValueError:
                continue  # entrada inválida -> se ignora, no concede acceso
        return False
