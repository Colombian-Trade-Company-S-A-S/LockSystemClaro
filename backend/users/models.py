"""Modelo de usuario del proyecto.

Decisiones clave (best practices para aplicaciones de larga vida):
- Identificador de login = **email** (no `username`).
- **UUID** como clave primaria (no enumerable, apto para sistemas distribuidos).
- `AbstractBaseUser + PermissionsMixin`: control total del esquema conservando
  el sistema de permisos/grupos de Django.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class Role(models.TextChoices):
    """Roles del sistema (perfiles de acceso).

    - ADMIN: todas las funcionalidades + gestión de usuarios y parametrizaciones.
    - OPERADOR: gestiones (habilitar/inhabilitar/enrolar/desenrolar), pines y reportes.
    - CONSULTA: validar estado (individual o masivo), entregar Códigos Pin y
      descargar reportes. NO es de solo lectura: entregar un pin deja el
      televisor Habilitado y lo sincroniza con el portal. No edita televisores
      ni cambia estados a mano (hallazgo H-08; ver OPERATOR_ACTIONS en
      televisores/api/views.py).
    """

    ADMIN = 'admin', _('Administrador')
    OPERADOR = 'operador', _('Operador')
    CONSULTA = 'consulta', _('Consulta')


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    email = models.EmailField(_('correo electrónico'), unique=True)
    first_name = models.CharField(_('nombres'), max_length=150, blank=True)
    last_name = models.CharField(_('apellidos'), max_length=150, blank=True)

    role = models.CharField(
        _('rol'),
        max_length=20,
        choices=Role.choices,
        default=Role.CONSULTA,
        help_text=_('Perfil de acceso: define qué módulos y acciones puede usar.'),
    )

    is_active = models.BooleanField(
        _('activo'),
        default=True,
        help_text=_('Desmarcar en lugar de borrar la cuenta.'),
    )
    is_staff = models.BooleanField(
        _('acceso al admin'),
        default=False,
        help_text=_('Permite el acceso al sitio de administración.'),
    )

    date_joined = models.DateTimeField(_('fecha de registro'), default=timezone.now)
    updated_at = models.DateTimeField(_('última actualización'), auto_now=True)

    # Preferencia de interfaz: color de acento elegido por el usuario. Se guarda
    # aquí (no solo en el navegador) para que la app arranque siempre con su
    # último color en cualquier dispositivo. El catálogo de acentos vive en el
    # front; aquí solo persistimos la clave elegida (p. ej. 'neutro', 'rosa').
    accent = models.CharField(
        _('color de acento'),
        max_length=20,
        default='neutro',
        blank=True,
        help_text=_('Preferencia de color de acento de la interfaz.'),
    )

    # Revocación server-side de tokens (logout real): los JWT llevan la versión
    # con la que se emitieron (claim `tv`). Al cerrar sesión se incrementa este
    # contador y todos los tokens anteriores dejan de validar. Es exacto (sin la
    # ambigüedad de segundos que tendría comparar por fecha de emisión).
    token_version = models.PositiveIntegerField(_('versión de token'), default=0)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: list[str] = []  # email y password ya son obligatorios

    class Meta:
        verbose_name = _('usuario')
        verbose_name_plural = _('usuarios')
        ordering = ['-date_joined']

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        # Mantiene el email siempre normalizado, incluso fuera del manager.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Roles / permisos de negocio
    # ------------------------------------------------------------------
    @property
    def is_admin_role(self) -> bool:
        """Administrador: superusuarios y usuarios con rol admin."""
        return self.is_superuser or self.role == Role.ADMIN

    @property
    def can_operate(self) -> bool:
        """Puede realizar gestiones de escritura (operador o administrador)."""
        return self.is_admin_role or self.role == Role.OPERADOR

    def revoke_tokens(self) -> None:
        """Invalida todos los tokens (access + refresh) emitidos hasta ahora.

        Se usa en el logout (cierre de sesión real): incrementa la versión, así
        que los tokens previos (que llevan la versión anterior) dejan de validar.
        """
        self.token_version = models.F('token_version') + 1
        self.save(update_fields=['token_version', 'updated_at'])
        self.refresh_from_db(fields=['token_version'])

    @property
    def full_name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip()

    def get_full_name(self) -> str:
        return self.full_name or self.email

    def get_short_name(self) -> str:
        return self.first_name or self.email


class SesionActiva(models.Model):
    """La única sesión que puede tener abierta un usuario a la vez.

    Regla de negocio: una cuenta = una sesión. Si alguien ya entró desde Chrome,
    no puede entrar desde otro navegador ni desde otro equipo hasta que cierre
    sesión o hasta que la suya caduque por inactividad.

    Cómo se ata un JWT a esta fila: los tokens llevan el claim `sid` con el
    identificador de aquí. La autenticación compara ambos, así que en cuanto
    esta fila cambia o desaparece, los tokens emitidos para la sesión anterior
    dejan de servir — sin depender de listas negras.

    `OneToOne`: la unicidad la garantiza la base de datos, no el código. Dos
    peticiones de login en paralelo no pueden crear dos sesiones.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sesion_activa',
        verbose_name=_('usuario'),
    )
    creada = models.DateTimeField(_('iniciada'), auto_now_add=True)
    # Se actualiza en cada renovación de token: es el latido que mantiene viva
    # la sesión. Si deja de latir el tiempo de la ventana, la sesión caduca y
    # otro navegador puede volver a entrar.
    ultima_actividad = models.DateTimeField(_('última actividad'), auto_now=True)

    # Contexto para poder decirle al usuario dónde tiene la sesión abierta.
    ip = models.GenericIPAddressField(_('IP'), null=True, blank=True)
    user_agent = models.TextField(_('navegador'), blank=True)

    # Identidad del navegador: 'IP|Chrome'. Es la otra mitad de la regla — una
    # cuenta no puede abrirse en dos navegadores, y un navegador no puede tener
    # abiertas dos cuentas. La calcula el servidor (ver `identidad_navegador`),
    # nunca el cliente.
    #
    # Por qué IP y no algo guardado en el navegador: Chrome aísla el
    # almacenamiento entre perfiles y en incógnito, así que un id de cliente
    # dejaba pasar "otro perfil del mismo Chrome" — justo lo que hay que
    # impedir. La IP es lo único que el servidor ve en común entre ellos.
    #
    # Vacío = no se pudo determinar (sin IP o sin navegador reconocible). En ese
    # caso no bloquea nada: preferimos dejar entrar a inventarnos una identidad.
    navegador_id = models.CharField(
        _('id de navegador'), max_length=64, blank=True, db_index=True
    )

    class Meta:
        verbose_name = _('sesión activa')
        verbose_name_plural = _('sesiones activas')
        ordering = ['-ultima_actividad']
        constraints = [
            # Unicidad en la base, no solo en el código: dos logins simultáneos
            # desde el mismo navegador no pueden crear dos sesiones. Parcial,
            # porque el vacío (identidad desconocida) debe poder repetirse.
            models.UniqueConstraint(
                fields=['navegador_id'],
                condition=~models.Q(navegador_id=''),
                name='sesion_unica_por_navegador',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.user.email} · {self.descripcion_dispositivo}'

    @property
    def vencida(self) -> bool:
        """True si lleva más de la ventana de inactividad sin dar señales."""
        limite = timedelta(minutes=settings.SESSION_INACTIVITY_MINUTOS)
        return timezone.now() - self.ultima_actividad > limite

    @property
    def descripcion_dispositivo(self) -> str:
        """Texto corto tipo 'Chrome en Windows' para el mensaje de error."""
        return describir_user_agent(self.user_agent)


# Fragmentos de User-Agent -> nombre legible. El orden importa: Edge y Opera
# incluyen "Chrome" en su cadena, y Chrome incluye "Safari".
_NAVEGADORES = (
    ('Edg/', 'Edge'),
    ('OPR/', 'Opera'),
    ('Firefox/', 'Firefox'),
    ('Chrome/', 'Chrome'),
    ('Safari/', 'Safari'),
)

_SISTEMAS = (
    ('Windows', 'Windows'),
    ('Android', 'Android'),
    ('iPhone', 'iPhone'),
    ('iPad', 'iPad'),
    ('Mac OS X', 'macOS'),
    ('Linux', 'Linux'),
)


def familia_navegador(user_agent: str) -> str:
    """'Chrome', 'Edge', … a partir del User-Agent. '' si no se reconoce."""
    return next((nombre for marca, nombre in _NAVEGADORES if marca in user_agent), '')


def identidad_navegador(*, ip: str | None, user_agent: str) -> str:
    """Identifica "este navegador en este equipo" como 'IP|Chrome'.

    A propósito NO distingue perfiles ni ventanas de incógnito: para la regla de
    negocio, dos perfiles del mismo Chrome en el mismo equipo son el mismo
    navegador. Sí distingue Chrome de Edge, que es lo que el usuario espera
    poder usar como salida ("entra desde otro navegador").

    Devuelve '' si falta cualquiera de las dos piezas: sin identidad fiable la
    regla no se aplica, en vez de bloquear a ciegas a todo el que comparta un
    dato a medias.
    """
    familia = familia_navegador(user_agent or '')
    if not ip or not familia:
        return ''
    return f'{ip}|{familia}'[:64]


def describir_user_agent(user_agent: str) -> str:
    """'Chrome en Windows' a partir de la cadena User-Agent.

    A ojo y sin librerías: solo alimenta un mensaje de ayuda ("ya tienes sesión
    abierta en…"), así que acertar el 95% de los casos basta y no justifica una
    dependencia nueva.
    """
    if not user_agent:
        return 'otro dispositivo'

    navegador = next(
        (nombre for marca, nombre in _NAVEGADORES if marca in user_agent), ''
    )
    sistema = next(
        (nombre for marca, nombre in _SISTEMAS if marca in user_agent), ''
    )

    if navegador and sistema:
        return f'{navegador} en {sistema}'
    return navegador or sistema or 'otro dispositivo'


class PasswordResetToken(models.Model):
    """Enlace de un solo uso para restablecer la contraseña olvidada.

    Decisiones de seguridad:

    - **Solo se guarda el hash.** El token viaja en la URL del correo; en la base
      queda su SHA-256. Si alguien lee la tabla no puede reconstruir enlaces
      válidos. Es el mismo criterio que ya usa `integracion.ApiKey`.
    - **SHA-256 y no un hasher lento** (Argon2/PBKDF2): el token son 256 bits
      aleatorios, no una contraseña adivinable; no hay nada que ralentizar, y sí
      hace falta poder buscarlo por índice.
    - **Un solo uso.** `usado_en` se sella al restablecer; un enlace reutilizado
      se rechaza aunque no haya vencido.
    - **Vigencia corta** (`settings.PASSWORD_RESET_MINUTOS`, 10 por defecto).
    - Al emitir uno nuevo se invalidan los anteriores del mismo usuario, para que
      pedir el correo dos veces no deje dos enlaces vivos.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='password_reset_tokens',
        verbose_name=_('usuario'),
    )
    token_hash = models.CharField(
        _('hash del token'), max_length=64, unique=True, editable=False,
    )
    creado = models.DateTimeField(_('creado'), auto_now_add=True)
    expira_en = models.DateTimeField(_('expira en'))
    usado_en = models.DateTimeField(_('usado en'), null=True, blank=True)

    # Auditoría: desde dónde se pidió y desde dónde se usó. Sirve para investigar
    # un restablecimiento sospechoso.
    ip_solicitud = models.GenericIPAddressField(
        _('IP de la solicitud'), null=True, blank=True,
    )
    ip_uso = models.GenericIPAddressField(_('IP de uso'), null=True, blank=True)

    class Meta:
        verbose_name = _('token de recuperación')
        verbose_name_plural = _('tokens de recuperación')
        ordering = ['-creado']
        indexes = [models.Index(fields=['user', '-creado'])]

    def __str__(self) -> str:
        return f'{self.user.email} · {self.creado:%Y-%m-%d %H:%M}'

    # ------------------------------------------------------------------
    # Emisión y verificación
    # ------------------------------------------------------------------
    @staticmethod
    def hash_de(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def emitir(cls, *, user, ip: str | None = None) -> tuple[PasswordResetToken, str]:
        """Crea un token nuevo. Devuelve (registro, token_en_claro).

        El token en claro solo existe aquí y en el correo: no vuelve a estar
        disponible después.
        """
        # Invalida los pendientes: si el usuario pidió el correo varias veces,
        # solo el último enlace debe funcionar.
        cls.objects.filter(user=user, usado_en__isnull=True).update(
            usado_en=timezone.now()
        )

        token = secrets.token_urlsafe(32)
        registro = cls.objects.create(
            user=user,
            token_hash=cls.hash_de(token),
            expira_en=timezone.now()
            + timedelta(minutes=settings.PASSWORD_RESET_MINUTOS),
            ip_solicitud=ip,
        )
        return registro, token

    @property
    def vencido(self) -> bool:
        return timezone.now() >= self.expira_en

    @property
    def usado(self) -> bool:
        return self.usado_en is not None

    @property
    def es_valido(self) -> bool:
        return not self.usado and not self.vencido and self.user.is_active

    def marcar_usado(self, *, ip: str | None = None) -> None:
        self.usado_en = timezone.now()
        self.ip_uso = ip
        self.save(update_fields=['usado_en', 'ip_uso'])
