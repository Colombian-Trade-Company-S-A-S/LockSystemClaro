"""Serializers de la app `users`.

Principios de seguridad aplicados:
- `password` es *write-only*: nunca se serializa de vuelta.
- Solo se exponen/aceptan campos seguros. `is_staff`, `is_superuser`, `groups`
  y `user_permissions` NO son asignables desde la API (anti mass-assignment /
  escalado de privilegios).
- La fortaleza de la contraseña se valida con las reglas de Django.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from auditoria.contexto import Contexto
from users.models import Role
from users.services import user_create, user_update

User = get_user_model()


def contexto_de(serializer: serializers.Serializer) -> Contexto | None:
    """Quién hace el cambio, para la bitácora. Las vistas genéricas de DRF
    pasan la request en el contexto del serializer."""
    request = serializer.context.get('request')
    return Contexto.de_request(request) if request is not None else None


def campo_nombre(**kwargs) -> serializers.CharField:
    """Nombres/apellidos tal y como los acepta la API: nunca vacíos.

    El modelo los deja `blank=True` (hay cuentas creadas antes de esta regla, y
    el superusuario de consola puede no tener nombre), pero por la API no se
    puede guardar uno en blanco: QA reportó que desde el perfil se podían borrar
    los apellidos y guardar, dejando la cuenta a medio identificar en toda la
    app — tabla de usuarios, auditoría, historial.

    `CharField` recorta los espacios antes de validar, así que "   " también se
    rechaza en lugar de colarse como un nombre válido.
    """
    return serializers.CharField(
        max_length=150,
        allow_blank=False,
        error_messages={
            'blank': 'Este campo es obligatorio.',
            'required': 'Este campo es obligatorio.',
        },
        **kwargs,
    )


class MeUpdateSerializer(serializers.ModelSerializer):
    """Edición del propio perfil: datos personales y preferencias (sin rol/permisos)."""

    # `required=False` porque el PATCH es parcial: guardar solo el color de
    # acento no debe obligar a reenviar el nombre. Pero si el campo viene, viene
    # con contenido.
    first_name = campo_nombre(required=False)
    last_name = campo_nombre(required=False)

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'accent')

    def update(self, instance: User, validated_data: dict) -> User:
        return user_update(user=instance, data=validated_data, contexto=contexto_de(self))


class ChangePasswordSerializer(serializers.Serializer):
    """Cambio de la propia contraseña: exige la actual y valida la nueva."""

    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128,
    )

    def validate_current_password(self, value: str) -> str:
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('La contraseña actual no es correcta.')
        return value

    def validate_new_password(self, value: str) -> str:
        user = self.context['request'].user
        validate_password(value, user=user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    """Solicitud del enlace de recuperación: solo el correo.

    No valida que la cuenta exista a propósito — ver
    `services.password_reset_solicitar`.
    """

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Restablecimiento con el token del enlace.

    La contraseña se valida contra el usuario **dueño del token** (no contra el
    que envía la petición, que es anónimo), para que las reglas de similitud con
    el correo y el nombre se apliquen de verdad. La vista inyecta ese usuario en
    el contexto.
    """

    token = serializers.CharField(write_only=True, trim_whitespace=True)
    new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128,
    )

    def validate_new_password(self, value: str) -> str:
        validate_password(value, user=self.context.get('target_user'))
        return value


class UserSerializer(serializers.ModelSerializer):
    """Representación pública/segura de un usuario (solo lectura)."""

    full_name = serializers.CharField(read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    sesion = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'full_name',
            'role',
            'role_display',
            'is_active',
            'date_joined',
            'accent',
            'sesion',
        )
        read_only_fields = fields

    def get_sesion(self, obj: User) -> dict | None:
        """Sesión abierta del usuario, o None.

        Se lee de la relación ya precargada (`user_list()` hace select_related)
        en lugar de consultar: si no, la tabla de usuarios haría una consulta
        por fila. Tampoco borra las caducadas aquí — una lectura no debería
        escribir; de eso se encarga `sesion_vigente` en el login.
        """
        sesion = getattr(obj, 'sesion_activa', None)
        if sesion is None or sesion.vencida:
            return None
        return {
            'dispositivo': sesion.descripcion_dispositivo,
            'iniciada': sesion.creada,
            'ultima_actividad': sesion.ultima_actividad,
            'ip': sesion.ip,
        }


class AdminUserCreateSerializer(serializers.ModelSerializer):
    """Alta de usuario por un administrador (asigna rol)."""

    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
        trim_whitespace=False,
        max_length=128,
    )
    role = serializers.ChoiceField(choices=Role.choices, default=Role.CONSULTA)
    first_name = campo_nombre()
    last_name = campo_nombre()

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'first_name', 'last_name', 'role')
        read_only_fields = ('id',)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Ya existe una cuenta con este correo.')
        return value

    def validate(self, attrs: dict) -> dict:
        temp_user = User(
            email=attrs.get('email', ''),
            first_name=attrs.get('first_name', ''),
            last_name=attrs.get('last_name', ''),
        )
        validate_password(attrs['password'], user=temp_user)
        return attrs

    def create(self, validated_data: dict) -> User:
        return user_create(**validated_data, contexto=contexto_de(self))


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """Edición de usuario por un administrador (nombre, rol, activo)."""

    role = serializers.ChoiceField(choices=Role.choices, required=False)
    # Parciales por la misma razón que en el perfil: el interruptor de "activo"
    # de la tabla manda solo `is_active`.
    first_name = campo_nombre(required=False)
    last_name = campo_nombre(required=False)

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'role', 'is_active')

    def update(self, instance: User, validated_data: dict) -> User:
        return user_update(user=instance, data=validated_data, contexto=contexto_de(self))
