"""Catálogo de eventos de la bitácora: la ÚNICA lista de lo que se registra.

`registrar()` rechaza cualquier acción que no esté aquí. Así nadie inventa un
nombre paralelo para algo que ya existe ("login_ok" junto a "login_exitoso") y
la pantalla de Auditoría puede ofrecer todos los filtros sin adivinar.

Para añadir un evento: una línea en ACCIONES con su categoría y su etiqueta. La
categoría sale de aquí, no la decide quien registra.
"""
from __future__ import annotations

from django.db import models


class Categoria(models.TextChoices):
    AUTENTICACION = 'autenticacion', 'Autenticación'
    USUARIOS = 'usuarios', 'Usuarios y permisos'
    TELEVISORES = 'televisores', 'Televisores'
    OPERACION = 'operacion', 'Estados y sincronización'
    PINES = 'pines', 'Códigos Pin'
    EXPORTACIONES = 'exportaciones', 'Exportaciones'
    INTEGRACION = 'integracion', 'API keys'


class Resultado(models.TextChoices):
    EXITO = 'exito', 'Éxito'
    FALLO = 'fallo', 'Fallo'
    # Se intentó algo para lo que no había permiso (403). Distinto de "fallo":
    # aquí el sistema funcionó y dijo que no.
    DENEGADO = 'denegado', 'Denegado'


class ActorTipo(models.TextChoices):
    USUARIO = 'usuario', 'Usuario'
    API_KEY = 'api_key', 'API key'
    # Sin identidad comprobada: un login fallido, un enlace de recuperación.
    ANONIMO = 'anonimo', 'Anónimo'
    # El propio sistema: una sesión que caduca, un proceso que termina solo.
    SISTEMA = 'sistema', 'Sistema'


C = Categoria

# accion -> (categoría, etiqueta legible)
ACCIONES: dict[str, tuple[str, str]] = {
    # --- Acceso al sistema (H-02) ---
    'login_exitoso': (C.AUTENTICACION, 'Inicio de sesión'),
    'login_fallido': (C.AUTENTICACION, 'Inicio de sesión fallido'),
    'logout': (C.AUTENTICACION, 'Cierre de sesión'),
    'sesion_expirada': (C.AUTENTICACION, 'Sesión expirada por inactividad'),
    'sesion_cerrada_por_admin': (C.AUTENTICACION, 'Sesión cerrada por un administrador'),
    'password_cambiado': (C.AUTENTICACION, 'Cambio de contraseña'),
    'password_reset_solicitado': (C.AUTENTICACION, 'Recuperación de contraseña solicitada'),
    'password_reset_completado': (C.AUTENTICACION, 'Contraseña restablecida con enlace'),

    # --- Gobierno de permisos (H-03) ---
    'usuario_creado': (C.USUARIOS, 'Usuario creado'),
    'usuario_actualizado': (C.USUARIOS, 'Datos de usuario modificados'),
    'perfil_actualizado': (C.USUARIOS, 'Perfil propio modificado'),
    'rol_cambiado': (C.USUARIOS, 'Cambio de rol'),
    'permisos_admin_cambiados': (C.USUARIOS, 'Cambio de permisos de administración'),
    'usuario_activado': (C.USUARIOS, 'Usuario activado'),
    'usuario_desactivado': (C.USUARIOS, 'Usuario desactivado'),
    'usuario_eliminado': (C.USUARIOS, 'Usuario eliminado'),
    # Un 403: alguien identificado intentó algo que su rol no permite.
    'acceso_denegado': (C.USUARIOS, 'Acción denegada por permisos'),

    # --- Inventario de televisores (H-04) ---
    'televisor_creado': (C.TELEVISORES, 'Televisor creado'),
    'televisor_editado': (C.TELEVISORES, 'Televisor editado'),
    'televisor_eliminado': (C.TELEVISORES, 'Televisor eliminado'),
    'importacion_masiva': (C.TELEVISORES, 'Carga masiva de televisores'),

    # --- Estados y sincronización con el portal (H-09, H-10) ---
    'estado_solicitado': (C.OPERACION, 'Cambio de estado solicitado'),
    'sincronizacion_terminada': (C.OPERACION, 'Sincronización terminada'),
    'sincronizacion_descartada': (C.OPERACION, 'Sincronización colgada descartada'),
    'lote_iniciado': (C.OPERACION, 'Sincronización masiva iniciada'),
    'lote_terminado': (C.OPERACION, 'Sincronización masiva terminada'),
    'validacion_masiva_iniciada': (C.OPERACION, 'Validación masiva iniciada'),
    'validacion_masiva_terminada': (C.OPERACION, 'Validación masiva terminada'),
    'lote_cancelado': (C.OPERACION, 'Lote cancelado'),

    # --- Códigos Pin ---
    'pin_entregado': (C.PINES, 'Código Pin entregado'),
    'pines_consultados': (C.PINES, 'Códigos Pin consultados'),

    # --- Salida de información (H-07) ---
    'exportacion': (C.EXPORTACIONES, 'Exportación de datos'),

    # --- Credenciales de integración (H-12) ---
    'api_key_creada': (C.INTEGRACION, 'API key creada'),
    'api_key_revocada': (C.INTEGRACION, 'API key revocada'),
    'api_key_modificada': (C.INTEGRACION, 'API key modificada'),
}


def categoria_de(accion: str) -> str:
    """Categoría de una acción. ValueError si la acción no está en el catálogo."""
    try:
        return ACCIONES[accion][0]
    except KeyError:
        raise ValueError(
            f'Acción de auditoría desconocida: {accion!r}. Añádela a '
            'auditoria/catalogo.py en vez de inventar un nombre suelto.'
        ) from None


def etiqueta_de(accion: str) -> str:
    return ACCIONES.get(accion, ('', accion))[1]
