"""Vistas HTTP de la app `users` (capa delgada: HTTP ↔ dominio)."""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import filters, generics, permissions, status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from auditoria.catalogo import Resultado
from auditoria.contexto import Contexto
from auditoria.services import registrar
from common.net import client_ip
from users.authentication import (
    SESSION_CLAIM,
    TOKEN_VERSION_CLAIM,
    token_esta_revocado,
)
from users.models import familia_navegador
from users.permissions import IsAdminRole
from users.selectors import user_list
from users.services import (
    NavegadorEnUso,
    SesionEnUso,
    password_reset_buscar,
    password_reset_confirmar,
    password_reset_solicitar,
    sesion_abrir,
    sesion_cerrar,
    sesion_latir,
    sesion_vigente,
    user_set_password,
)

from .serializers import (
    AdminUserCreateSerializer,
    AdminUserUpdateSerializer,
    ChangePasswordSerializer,
    MeUpdateSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserSerializer,
)

User = get_user_model()

logger = logging.getLogger(__name__)


# NOTA: no existe una vista de auto-registro público. Las cuentas las crea un
# Administrador (`AdminUserListCreateView`, POST /api/usuarios/). Exponer un alta
# pública daría a desconocidos acceso de lectura a dispositivos y PINs.


class MeView(generics.RetrieveUpdateAPIView):
    """Perfil del usuario autenticado: consulta (GET) y edición propia (PATCH).

    Solo permite editar datos personales (nombre/apellido); el rol y los
    permisos NO son auto-editables (anti escalado de privilegios).
    """

    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return MeUpdateSerializer
        return UserSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        # Responde siempre con la representación segura y completa del perfil.
        return Response(UserSerializer(self.get_object()).data)


class VersionedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Incrusta la versión de token vigente del usuario en el JWT (claim `tv`).

    Permite la revocación server-side: ver users/authentication.py.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token[TOKEN_VERSION_CLAIM] = user.token_version
        return token


def emitir_par_de_tokens(user, *, sid) -> dict[str, str]:
    """Par access/refresh atado a una sesión concreta (claim `sid`).

    SimpleJWT copia los claims personalizados del refresh al access que deriva
    de él, así que basta con ponerlos una vez.
    """
    refresh = VersionedTokenObtainPairSerializer.get_token(user)
    refresh[SESSION_CLAIM] = str(sid)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


class LoginView(TokenObtainPairView):
    """Obtiene el par de tokens (access/refresh) con email + password.

    **Sesión única**, en las dos direcciones, y ambas responden 409:
    - `sesion_activa`: la cuenta ya está abierta en otro navegador o equipo.
    - `navegador_ocupado`: este navegador ya tiene abierta otra cuenta.

    En ninguno de los dos casos se toca la sesión que ya existe: quien está
    trabajando no pierde lo que hace.

    Que la única forma de desbloquearse sea cerrar sesión (o esperar a que
    caduque por inactividad) es la intención de la regla, no un descuido. Un
    administrador puede forzar el cierre desde /usuarios si alguien se queda
    fuera por haber cerrado el navegador sin salir.
    """

    serializer_class = VersionedTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    @staticmethod
    def _correo_tecleado(request) -> str:
        # Esto corre también en `throttled`, ANTES de que el serializer valide
        # nada: el cuerpo puede ser una lista, y el correo llevar un NUL, que
        # Postgres rechaza hasta en una consulta.
        datos = request.data
        correo = datos.get('email') if isinstance(datos, dict) else ''
        if not isinstance(correo, str):
            return ''
        return correo.replace('\x00', '').strip()[:255]

    @classmethod
    def _cuenta_tecleada(cls, request):
        correo = cls._correo_tecleado(request)
        return User.objects.filter(email__iexact=correo).first() if correo else None

    def _registrar_fallo(
        self, request, motivo: str, *, user=None, cuenta=None, **detalle
    ) -> None:
        """Ingreso fallido en la bitácora (H-02). El motivo va SOLO aquí: la
        respuesta HTTP sigue siendo la genérica, para no decirle a un extraño si
        el correo existe. Se guarda el correo tecleado aunque no haya cuenta.

        Con `user`, las credenciales eran buenas (la sesión estaba ocupada): el
        actor es esa persona. Sin él, es un anónimo que dijo ser ese correo, y
        la cuenta a la que apuntaba (si existe) queda como objeto.
        """
        correo = self._correo_tecleado(request)
        if user is not None:
            cuenta = user
        elif cuenta is None:
            cuenta = self._cuenta_tecleada(request)
        registrar(
            'login_fallido',
            contexto=(
                Contexto.de_usuario(user, request)
                if user is not None
                else Contexto.anonimo(request, correo)
            ),
            resultado=Resultado.FALLO,
            objeto=cuenta,
            motivo=motivo,
            **detalle,
        )

    def throttled(self, request, wait):
        # Superar el límite de intentos es la señal más clara de fuerza bruta.
        self._registrar_fallo(request, 'demasiados intentos (límite de frecuencia)')
        super().throttled(request, wait)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        # Credenciales primero: si son incorrectas debe responder 401 aunque la
        # cuenta tenga sesión abierta. Al revés, el 409 le confirmaría a un
        # desconocido que ese correo existe y está en uso.
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(str(exc)) from exc
        except AuthenticationFailed:
            cuenta = self._cuenta_tecleada(request)
            if cuenta is None:
                motivo = 'cuenta inexistente'
            elif not cuenta.is_active:
                motivo = 'cuenta inactiva'
            else:
                motivo = 'contraseña incorrecta'
            self._registrar_fallo(request, motivo, cuenta=cuenta)
            raise

        user = serializer.user
        minutos = settings.SESSION_INACTIVITY_MINUTOS

        try:
            sesion = sesion_abrir(
                user=user,
                ip=client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )
        except SesionEnUso as exc:
            activa = exc.sesion
            self._registrar_fallo(
                request,
                'la cuenta ya tiene una sesión abierta',
                user=user,
                dispositivo=activa.descripcion_dispositivo,
                ip_sesion=activa.ip,
            )
            return Response(
                {
                    'detail': (
                        f'Esta cuenta ya tiene una sesión abierta en '
                        f'{activa.descripcion_dispositivo}. Cierra sesión allí '
                        f'para poder entrar aquí.'
                    ),
                    'code': 'sesion_activa',
                    'dispositivo': activa.descripcion_dispositivo,
                    'iniciada': activa.creada,
                    'ultima_actividad': activa.ultima_actividad,
                    # Para que la interfaz pueda decir cuánto falta si el otro
                    # equipo simplemente se quedó abierto y sin usar.
                    'expira_por_inactividad_minutos': minutos,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except NavegadorEnUso as exc:
            activa = exc.sesion
            self._registrar_fallo(
                request,
                'el navegador ya tiene abierta otra cuenta',
                user=user,
                cuenta_ocupante=activa.user.email,
            )
            # El correo va ofuscado: quien está frente a esta pantalla no es
            # necesariamente el dueño de la sesión abierta, y basta con que
            # reconozca la cuenta para saber a quién pedirle que salga.
            return Response(
                {
                    'detail': (
                        f'Este equipo ya tiene una sesión abierta en '
                        f'{familia_navegador(activa.user_agent) or "este navegador"} '
                        f'con la cuenta {_email_ofuscado(activa.user.email)}. '
                        f'Cierra esa sesión antes de entrar con otra cuenta, o '
                        f'entra desde otro navegador.'
                    ),
                    'code': 'navegador_ocupado',
                    'navegador': familia_navegador(activa.user_agent),
                    'cuenta': _email_ofuscado(activa.user.email),
                    'iniciada': activa.creada,
                    'ultima_actividad': activa.ultima_actividad,
                    'expira_por_inactividad_minutos': minutos,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # La fila de sesión activa se sobrescribe y se borra al salir: esto es
        # lo que queda de que entró (H-02).
        registrar(
            'login_exitoso',
            contexto=Contexto.de_usuario(user, request),
            objeto=user,
            sesion=str(sesion.id),
            dispositivo=sesion.descripcion_dispositivo,
        )
        return Response(emitir_par_de_tokens(user, sid=sesion.id))


class RevocationAwareTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh que respeta la revocación server-side y la sesión única.

    Rechaza un refresh emitido antes del corte del usuario, de una cuenta
    inactiva/eliminada, o de una sesión que ya no es la vigente.

    Además es el **latido** de la sesión: cada renovación marca actividad, y es
    lo que mantiene viva la sesión frente a la ventana de inactividad.
    """

    def validate(self, attrs):
        try:
            refresh = RefreshToken(attrs['refresh'])
        except TokenError as exc:
            raise InvalidToken(str(exc)) from exc

        user = User.objects.filter(id=refresh.get('user_id')).first()
        if user is None or not user.is_active:
            raise InvalidToken('La cuenta no está disponible.')
        if token_esta_revocado(user, refresh):
            raise InvalidToken('La sesión fue cerrada. Inicia sesión de nuevo.')
        if not sesion_latir(user=user, sid=refresh.get(SESSION_CLAIM)):
            raise InvalidToken('Tu sesión ya no está activa. Inicia sesión de nuevo.')

        # El refresh rotado conserva los claims personalizados (`tv` y `sid`):
        # SimpleJWT reutiliza el mismo token cambiándole jti/exp/iat.
        return super().validate(attrs)


class RefreshView(TokenRefreshView):
    """Renueva el access token a partir de un refresh válido (y no revocado)."""

    serializer_class = RevocationAwareTokenRefreshSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class LogoutView(APIView):
    """Cierre de sesión real: revoca los tokens del usuario en el servidor.

    A partir de aquí, cualquier access/refresh emitido antes deja de ser válido
    (incluye los que hubieran podido filtrarse). El cliente además descarta los
    suyos localmente. Libera también la sesión única, para poder volver a entrar
    desde cualquier navegador.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        request.user.revoke_tokens()
        sesion_cerrar(request.user)
        # El navegador avisa si el cierre fue suyo por inactividad
        # (`motivo: 'inactividad'`); si no, lo pidió la persona.
        datos = request.data if isinstance(request.data, dict) else {}
        por_inactividad = datos.get('motivo') == 'inactividad'
        registrar(
            'sesion_expirada' if por_inactividad else 'logout',
            contexto=Contexto.de_request(request),
            objeto=request.user,
            detectada_por='navegador' if por_inactividad else None,
        )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class ChangePasswordView(APIView):
    """Cambio de la propia contraseña.

    Al cambiarla se **revocan** las demás sesiones (bump de versión de token) y
    se **re-emite** un par de tokens para la sesión actual, para no cerrarla.
    Throttle 'login' para limitar intentos contra la contraseña actual.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={'request': request}
        )
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as exc:
            # Fallar la contraseña ACTUAL con una sesión abierta es alguien
            # probando contraseñas desde un equipo desatendido: queda en la
            # bitácora. Una contraseña nueva débil no, eso es solo un formulario.
            if isinstance(exc.detail, dict) and 'current_password' in exc.detail:
                registrar(
                    'password_cambiado',
                    contexto=Contexto.de_request(request),
                    resultado=Resultado.FALLO,
                    objeto=request.user,
                    motivo='contraseña actual incorrecta',
                )
            raise

        user = request.user
        user_set_password(
            user=user, raw_password=serializer.validated_data['new_password']
        )
        registrar('password_cambiado', contexto=Contexto.de_request(request), objeto=user)
        # Invalida cualquier token anterior (otras sesiones / posibles filtrados).
        user.revoke_tokens()
        # Re-emite para el cliente actual con la nueva versión de token. Se
        # conserva el `sid`: la sesión sigue siendo la misma, solo cambian los
        # tokens, así que cambiar la contraseña no obliga a volver a entrar.
        sid = (request.auth or {}).get(SESSION_CLAIM)
        return Response(emitir_par_de_tokens(user, sid=sid))


# ---------------------------------------------------------------------------
# Recuperación de contraseña (usuario no autenticado)
# ---------------------------------------------------------------------------
# Estas tres vistas son públicas (AllowAny) porque quien las usa, por
# definición, no puede iniciar sesión. La protección es: respuesta genérica
# (no revela qué correos existen), throttle agresivo y enlace de un solo uso
# con 10 minutos de vida.

class PasswordResetRequestView(APIView):
    """Pide el enlace de recuperación por correo.

    Responde 202 SIEMPRE, exista o no la cuenta: una respuesta distinta
    convertiría este endpoint en un verificador de correos registrados.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correo = serializer.validated_data['email']

        # La bitácora sí distingue los casos (la respuesta no): una racha de
        # pedidos para correos sin cuenta es alguien sondeando qué cuentas hay.
        resultado, motivo, cuenta = Resultado.EXITO, None, None
        try:
            cuenta = password_reset_solicitar(email=correo, ip=client_ip(request))
            if cuenta is None:
                resultado, motivo = Resultado.FALLO, 'el correo no tiene una cuenta activa'
        except Exception:
            # Un fallo de envío (Gmail caído, token revocado) no debe distinguirse
            # de un correo inexistente: se registra para operaciones y al cliente
            # se le responde igual.
            logger.exception('Fallo al enviar el correo de recuperación.')
            resultado, motivo = Resultado.FALLO, 'no se pudo enviar el correo'
        registrar(
            'password_reset_solicitado',
            contexto=Contexto.anonimo(request, correo),
            resultado=resultado,
            objeto=cuenta,
            motivo=motivo,
        )

        return Response(
            {
                'detail': (
                    'Si el correo corresponde a una cuenta activa, te enviamos '
                    'un enlace para restablecer la contraseña.'
                ),
                'expira_minutos': settings.PASSWORD_RESET_MINUTOS,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetValidateView(APIView):
    """Comprueba un token antes de mostrar el formulario.

    Permite que la pantalla diga "este enlace venció" nada más abrirla, en vez
    de hacer que el usuario escriba una contraseña nueva para recién entonces
    rechazarla.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def get(self, request):
        registro = password_reset_buscar(request.query_params.get('token', ''))
        if registro is None or not registro.es_valido:
            # Motivo para la interfaz. No filtra nada: quien tiene el token ya
            # lo tiene, y sin token la respuesta es siempre 'invalido'.
            if registro is None:
                motivo = 'invalido'
            elif registro.usado:
                motivo = 'usado'
            elif registro.vencido:
                motivo = 'vencido'
            else:
                motivo = 'invalido'
            return Response(
                {'valido': False, 'motivo': motivo},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'valido': True,
            # El correo (parcialmente oculto) confirma al usuario que el enlace
            # es de su cuenta, sin exponerlo entero a quien intercepte la URL.
            'email': _email_ofuscado(registro.user.email),
            'expira_en': registro.expira_en,
            # Tiempo RELATIVO para la cuenta atrás de la interfaz. Con la fecha
            # absoluta, un navegador con el reloj desfasado daría el enlace por
            # vencido nada más abrirlo; con segundos no hay reloj que valga.
            'segundos_restantes': max(
                0, int((registro.expira_en - timezone.now()).total_seconds())
            ),
        })


class PasswordResetConfirmView(APIView):
    """Fija la nueva contraseña y consume el enlace."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        # El token se lee antes de validar el serializer para poder aplicar las
        # reglas de contraseña contra el usuario dueño del enlace.
        registro = password_reset_buscar(str(request.data.get('token', '')))
        if registro is None or not registro.es_valido:
            registrar(
                'password_reset_completado',
                contexto=Contexto.anonimo(request),
                resultado=Resultado.FALLO,
                objeto=registro.user if registro is not None else None,
                motivo='enlace inválido, usado o vencido',
            )
            raise ValidationError({
                'token': [
                    'El enlace no es válido o ya venció. Solicita uno nuevo.'
                ]
            })

        serializer = PasswordResetConfirmSerializer(
            data=request.data, context={'target_user': registro.user}
        )
        serializer.is_valid(raise_exception=True)

        try:
            user = password_reset_confirmar(
                registro=registro,
                raw_password=serializer.validated_data['new_password'],
                ip=client_ip(request),
            )
        except ValueError as exc:
            # Carrera: el enlace se consumió entre la comprobación y el commit.
            raise ValidationError({'token': [str(exc)]}) from exc

        # Actúa como el titular de la cuenta: tener el enlace prueba acceso a
        # su correo.
        registrar(
            'password_reset_completado',
            contexto=Contexto.de_usuario(user, request),
            objeto=user,
        )
        return Response({
            'detail': 'Tu contraseña fue actualizada. Ya puedes iniciar sesión.'
        })


def _email_ofuscado(email: str) -> str:
    """`daniel96correa@gmail.com` -> `da**********@gmail.com`."""
    usuario, _, dominio = email.partition('@')
    if len(usuario) <= 2:
        visible = usuario[:1]
    else:
        visible = usuario[:2]
    return f'{visible}{"*" * max(len(usuario) - len(visible), 1)}@{dominio}'


# ---------------------------------------------------------------------------
# Gestión de usuarios (solo Administrador)
# ---------------------------------------------------------------------------
class AdminUserListCreateView(generics.ListCreateAPIView):
    """Lista y crea usuarios. Reservado a administradores."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]
    queryset = user_list().order_by('-date_joined')
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['email', 'first_name', 'last_name']
    ordering_fields = ['email', 'date_joined', 'role']

    def get_queryset(self):
        qs = super().get_queryset()
        # ?activos=1 -> solo cuentas activas. La tabla de usuarios oculta los
        # inactivos por defecto y los muestra con el botón "Ver inactivos".
        if self.request.query_params.get('activos') in ('1', 'true'):
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AdminUserCreateSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # Respondemos con la vista segura (sin contraseña, con rol legible).
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class AdminUserDetailView(generics.RetrieveUpdateAPIView):
    """Consulta y edita un usuario (rol, nombre, activo). Solo administradores."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]
    queryset = user_list()

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return AdminUserUpdateSerializer
        return UserSerializer

    def perform_update(self, serializer):
        target = self.get_object()
        # Evita que un administrador se bloquee a sí mismo (perder acceso admin
        # o desactivar su propia cuenta) desde esta pantalla.
        if target == self.request.user:
            data = serializer.validated_data
            if data.get('role', target.role) != target.role and not target.is_superuser:
                raise ValidationError('No puedes cambiar tu propio rol.')
            if data.get('is_active', target.is_active) is False:
                raise ValidationError('No puedes desactivar tu propia cuenta.')
        serializer.save()

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        # Devuelve siempre la representación segura y completa del usuario.
        return Response(UserSerializer(self.get_object()).data)


class AdminCerrarSesionView(APIView):
    """Fuerza el cierre de la sesión de un usuario. Solo administradores.

    Existe porque la sesión única puede dejar a alguien fuera: si cierra el
    navegador sin salir, su sesión sigue contando como abierta hasta que caduca
    por inactividad. Esto lo desbloquea al instante en vez de hacerle esperar.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request, pk):
        objetivo = generics.get_object_or_404(user_list(), pk=pk)

        sesion = sesion_vigente(objetivo)
        if sesion is None:
            return Response({
                'detail': 'Ese usuario no tiene ninguna sesión abierta.',
                'cerrada': False,
            })

        dispositivo = sesion.descripcion_dispositivo
        sesion_cerrar(objetivo)
        # También los tokens: sin esto, su access actual seguiría sirviendo
        # hasta vencer.
        objetivo.revoke_tokens()

        registrar(
            'sesion_cerrada_por_admin',
            contexto=Contexto.de_request(request),
            objeto=objetivo,
            dispositivo=dispositivo,
            ip_sesion=sesion.ip,
        )
        logger.info(
            'Sesión de %s cerrada por %s (admin).', objetivo.email, request.user.email
        )
        return Response({
            'detail': f'Sesión cerrada ({dispositivo}). Ya puede iniciar sesión.',
            'cerrada': True,
        })
