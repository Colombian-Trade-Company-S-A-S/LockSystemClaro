"""Capa de servicios: lógica de negocio de **escritura** sobre usuarios.

Reglas de esta capa:
- Toda mutación del estado pasa por aquí (no desde las vistas ni los modelos).
- Las operaciones que tocan varias filas/tablas son transaccionales.
- Devuelve entidades del dominio (instancias de modelo), no respuestas HTTP.
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from auditoria.contexto import Contexto
from auditoria.services import foto, registrar

from .emails import enviar_recuperacion_password
from .models import (
    PasswordResetToken,
    Role,
    SesionActiva,
    User,
    describir_user_agent,
    identidad_navegador,
)

logger = logging.getLogger(__name__)

# Lo que define a una cuenta y sus permisos, para la bitácora. Nunca la
# contraseña ni su hash.
CAMPOS_USUARIO = (
    'email',
    'first_name',
    'last_name',
    'role',
    'is_active',
    'is_staff',
    'is_superuser',
)


@transaction.atomic
def user_create(
    *,
    email: str,
    password: str | None = None,
    first_name: str = '',
    last_name: str = '',
    role: str = Role.CONSULTA,
    is_active: bool = True,
    is_staff: bool = False,
    contexto: Contexto | None = None,
) -> User:
    """Crea un usuario estándar aplicando las validaciones del modelo.

    Deja el alta en la bitácora (hallazgo H-03) con el rol con el que nace: es
    el primer eslabón de «quién le dio permiso».
    """
    user = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=role,
        is_active=is_active,
        is_staff=is_staff,
    )
    user.full_clean(exclude=['password'])
    user.set_password(password)
    user.save()
    registrar(
        'usuario_creado',
        contexto=contexto,
        objeto=user,
        despues=foto(user, CAMPOS_USUARIO),
    )
    return user


@transaction.atomic
def user_set_password(*, user: User, raw_password: str) -> User:
    """Fija una nueva contraseña (ya validada por el serializer)."""
    user.set_password(raw_password)
    user.save(update_fields=['password', 'updated_at'])
    return user


@transaction.atomic
def user_update(*, user: User, data: dict, contexto: Contexto | None = None) -> User:
    """Actualiza campos permitidos de un usuario existente.

    La lista de campos cambiados, que ya se armaba para guardar solo lo
    necesario, ahora además va a la bitácora (hallazgo H-03). El cambio de rol
    y el de activación van como eventos propios: son los que responden «quién
    le dio permiso» y «quién le quitó el acceso».
    """
    updatable_fields = {'first_name', 'last_name', 'role', 'is_active', 'accent'}
    changed = []
    antes = {}

    for field, value in data.items():
        if field in updatable_fields and getattr(user, field) != value:
            antes[field] = getattr(user, field)
            setattr(user, field, value)
            changed.append(field)

    if changed:
        user.full_clean(exclude=['password'])
        user.save(update_fields=[*changed, 'updated_at'])
        registrar_cambios_usuario(user, antes, contexto or Contexto.sistema())

    # Desactivar una cuenta debe echar fuera a quien la esté usando ahora mismo,
    # no solo impedir el próximo inicio de sesión.
    if 'is_active' in changed and not user.is_active:
        user.revoke_tokens()
        sesion_cerrar(user)

    return user


def registrar_cambios_usuario(user: User, antes: dict, contexto: Contexto) -> None:
    """Un evento por tipo de cambio, a partir de los valores previos de los
    campos que cambiaron. Lo usan la API y el admin de Django.

    El color de acento es una preferencia de pantalla: no es un cambio que
    nadie necesite auditar.
    """
    if 'role' in antes:
        registrar(
            'rol_cambiado',
            contexto=contexto,
            objeto=user,
            antes={'role': antes['role']},
            despues={'role': user.role},
        )
    if 'is_active' in antes:
        registrar(
            'usuario_activado' if user.is_active else 'usuario_desactivado',
            contexto=contexto,
            objeto=user,
            antes={'is_active': antes['is_active']},
            despues={'is_active': user.is_active},
        )
    # Solo se pueden tocar desde el admin de Django; la API no los expone.
    admin = [c for c in ('is_staff', 'is_superuser') if c in antes]
    if admin:
        registrar(
            'permisos_admin_cambiados',
            contexto=contexto,
            objeto=user,
            antes={c: antes[c] for c in admin},
            despues={c: getattr(user, c) for c in admin},
        )
    datos = [c for c in ('email', 'first_name', 'last_name') if c in antes]
    if datos:
        propio = contexto.usuario_id is not None and str(contexto.usuario_id) == str(user.pk)
        registrar(
            'perfil_actualizado' if propio else 'usuario_actualizado',
            contexto=contexto,
            objeto=user,
            antes={c: antes[c] for c in datos},
            despues={c: getattr(user, c) for c in datos},
        )


# ---------------------------------------------------------------------------
# Sesión única por usuario Y por navegador
# ---------------------------------------------------------------------------
# La regla tiene dos caras y las dos se comprueban al abrir sesión:
#   1. Una cuenta = un navegador. Si entraste en Chrome, no puedes entrar con la
#      misma cuenta en Edge  ->  SesionEnUso.
#   2. Un navegador = una cuenta. Si en ese Chrome ya hay una sesión abierta de
#      otra persona, esa otra cuenta no puede entrar ahí  ->  NavegadorEnUso.
# En ambos casos el bloqueo dura lo que dure la sesión: al cerrarla (o al
# caducar por inactividad) el navegador y la cuenta quedan libres otra vez.
class SesionEnUso(Exception):
    """Ya hay una sesión abierta para esa cuenta en otro navegador/equipo."""

    def __init__(self, sesion: SesionActiva) -> None:
        self.sesion = sesion
        super().__init__('Ya hay una sesión activa para esta cuenta.')


class NavegadorEnUso(Exception):
    """Este navegador ya tiene abierta la sesión de OTRA cuenta."""

    def __init__(self, sesion: SesionActiva) -> None:
        self.sesion = sesion
        super().__init__('Este navegador ya tiene una sesión abierta.')


def _expirar(sesion: SesionActiva) -> None:
    """Borra una sesión caducada y deja constancia de que expiró (H-02).

    La caducidad se detecta tarde, cuando alguien vuelve a preguntar por la
    sesión, así que el momento del evento es el de la detección; la hora real
    del corte es `ultima_actividad` + la ventana de inactividad, y va en el
    detalle. Solo registra quien efectivamente la borró: si dos peticiones la
    detectan a la vez, queda un evento, no dos.
    """
    borradas, _ = SesionActiva.objects.filter(pk=sesion.pk).delete()
    if not borradas:
        return
    registrar(
        'sesion_expirada',
        objeto=sesion.user,
        detectada_por='servidor',
        sesion=str(sesion.pk),
        ip_sesion=sesion.ip,
        dispositivo=describir_user_agent(sesion.user_agent),
        iniciada=sesion.creada,
        ultima_actividad=sesion.ultima_actividad,
    )


def sesion_vigente(user: User) -> SesionActiva | None:
    """Sesión abierta del usuario, o None si no tiene o si ya caducó.

    Limpia de paso las caducadas: así una sesión que quedó colgada (el usuario
    cerró el navegador sin salir) deja de bloquear la cuenta en cuanto pasa la
    ventana de inactividad, sin necesitar una tarea programada.
    """
    sesion = SesionActiva.objects.filter(user=user).first()
    if sesion is None:
        return None
    if sesion.vencida:
        _expirar(sesion)
        return None
    return sesion


def sesion_de_navegador(navegador_id: str | None) -> SesionActiva | None:
    """Sesión abierta en ese navegador, o None si no hay o si ya caducó.

    Igual que `sesion_vigente`, limpia la caducada de paso: un navegador donde
    alguien cerró la ventana sin salir se libera solo al pasar la ventana de
    inactividad.
    """
    if not navegador_id:
        return None
    sesion = SesionActiva.objects.select_related('user').filter(
        navegador_id=navegador_id
    ).first()
    if sesion is None:
        return None
    if sesion.vencida:
        _expirar(sesion)
        return None
    return sesion


@transaction.atomic
def sesion_abrir(
    *, user: User, ip: str | None = None, user_agent: str = ''
) -> SesionActiva:
    """Abre la sesión del usuario. Falla si la cuenta o el navegador están en uso.

    `select_for_update` sobre el usuario serializa dos logins simultáneos: sin
    él, ambos podrían comprobar "no hay sesión" a la vez y el segundo se
    estrellaría contra la restricción de unicidad con un error feo.
    """
    User.objects.select_for_update().filter(pk=user.pk).first()

    existente = sesion_vigente(user)
    if existente is not None:
        raise SesionEnUso(existente)

    # La cuenta está libre; falta que lo esté el navegador. Solo estorba si la
    # sesión que hay ahí es de OTRA persona: si fuera del mismo usuario, la
    # comprobación anterior ya habría cortado.
    navegador_id = identidad_navegador(ip=ip, user_agent=user_agent)
    ocupante = sesion_de_navegador(navegador_id)
    if ocupante is not None:
        raise NavegadorEnUso(ocupante)

    try:
        # `atomic` anidado: crea un savepoint, así un choque contra la
        # restricción no deja la transacción entera rota y podemos consultar
        # quién ganó la carrera.
        with transaction.atomic():
            return SesionActiva.objects.create(
                user=user,
                ip=ip,
                user_agent=(user_agent or '')[:500],
                navegador_id=navegador_id,
            )
    except IntegrityError:
        ocupante = sesion_de_navegador(navegador_id)
        if ocupante is None:
            raise
        raise NavegadorEnUso(ocupante) from None


def sesion_latir(*, user: User, sid: str | None) -> bool:
    """Marca actividad en la sesión. False si `sid` no es la sesión vigente.

    Devolver False significa que el token viene de una sesión que ya fue
    cerrada o reemplazada: quien lo presente debe volver al login.
    """
    if not sid:
        return False
    sesion = sesion_vigente(user)
    if sesion is None or str(sesion.id) != str(sid):
        return False
    # `auto_now` en ultima_actividad: guardar el campo basta para refrescarlo.
    sesion.save(update_fields=['ultima_actividad'])
    return True


def sesion_cerrar(user: User) -> None:
    """Cierra la sesión del usuario (logout, o cierre forzado por un admin)."""
    SesionActiva.objects.filter(user=user).delete()


# ---------------------------------------------------------------------------
# Recuperación de contraseña (enlace de un solo uso enviado por correo)
# ---------------------------------------------------------------------------
def password_reset_solicitar(*, email: str, ip: str | None = None) -> User | None:
    """Emite un enlace de recuperación y lo envía por correo.

    **No revela si la cuenta existe.** Si el correo no corresponde a ninguna
    cuenta activa la función no hace nada y la vista responde igual que en el
    caso normal: de lo contrario el formulario sería un oráculo para averiguar
    qué correos están registrados.

    Devuelve la cuenta (o None) solo para que la vista lo anote en la bitácora;
    nunca para responder distinto.
    """
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is None:
        logger.info('Recuperación solicitada para un correo sin cuenta activa.')
        return None

    # El envío queda FUERA de la transacción del token: si el correo falla, no
    # queremos dejar en la base un token emitido que nadie recibió.
    with transaction.atomic():
        _, token = PasswordResetToken.emitir(user=user, ip=ip)

    enviar_recuperacion_password(user=user, token=token)
    return user


def password_reset_buscar(token: str) -> PasswordResetToken | None:
    """Localiza un token por su valor en claro. None si no existe."""
    if not token:
        return None
    return (
        PasswordResetToken.objects
        .select_related('user')
        .filter(token_hash=PasswordResetToken.hash_de(token))
        .first()
    )


@transaction.atomic
def password_reset_confirmar(
    *, registro: PasswordResetToken, raw_password: str, ip: str | None = None
) -> User:
    """Aplica la nueva contraseña y consume el enlace.

    Se bloquea la fila del token durante la transacción: sin eso, dos peticiones
    simultáneas con el mismo enlace podrían pasar ambas la comprobación de "no
    usado" y gastarlo dos veces.
    """
    registro = (
        PasswordResetToken.objects
        .select_for_update()
        .select_related('user')
        .get(pk=registro.pk)
    )
    if not registro.es_valido:
        raise ValueError('El enlace ya no es válido.')

    user = registro.user
    user_set_password(user=user, raw_password=raw_password)
    registro.marcar_usado(ip=ip)

    # Cierra cualquier sesión abierta: si la cuenta estaba comprometida, el
    # atacante queda fuera en el mismo momento del restablecimiento. Además
    # libera la sesión única, para poder entrar con la contraseña nueva.
    user.revoke_tokens()
    sesion_cerrar(user)
    return user
