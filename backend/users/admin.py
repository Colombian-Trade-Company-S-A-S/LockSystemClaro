from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from auditoria.contexto import Contexto
from auditoria.services import describir, foto, registrar

from .models import PasswordResetToken, SesionActiva, User
from .services import CAMPOS_USUARIO, registrar_cambios_usuario


class UserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('email',)


class UserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    ordering = ('-date_joined',)
    list_display = ('email', 'full_name', 'role', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('role', 'is_active', 'is_staff', 'is_superuser', 'groups')
    search_fields = ('email', 'first_name', 'last_name')
    readonly_fields = ('date_joined', 'updated_at', 'last_login')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Datos personales'), {'fields': ('first_name', 'last_name')}),
        (_('Rol'), {'fields': ('role',)}),
        (_('Permisos'), {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            ),
        }),
        (_('Fechas'), {'fields': ('last_login', 'date_joined', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2'),
        }),
    )

    # El admin es la única vía que puede tocar is_staff/is_superuser: sin esto,
    # un superusuario creado desde aquí no dejaba ningún rastro (H-03).
    def save_model(self, request, obj, form, change):
        contexto = Contexto.de_request(request)
        with transaction.atomic():
            antes = foto(User.objects.get(pk=obj.pk), CAMPOS_USUARIO) if change else None
            super().save_model(request, obj, form, change)
            if not change:
                registrar(
                    'usuario_creado',
                    contexto=contexto,
                    objeto=obj,
                    despues=foto(obj, CAMPOS_USUARIO),
                    origen='admin',
                )
                return
            despues = foto(obj, CAMPOS_USUARIO)
            cambiados = {c: antes[c] for c in CAMPOS_USUARIO if antes[c] != despues[c]}
            registrar_cambios_usuario(obj, cambiados, contexto)

    def delete_model(self, request, obj):
        self._borrar(request, [obj])

    def delete_queryset(self, request, queryset):
        self._borrar(request, list(queryset))

    def _borrar(self, request, usuarios):
        """Borrar una cuenta: el evento guarda quién era y qué permisos tenía,
        porque después la fila ya no existe para preguntárselo."""
        contexto = Contexto.de_request(request)
        with transaction.atomic():
            for user in usuarios:
                tipo, objeto_id, etiqueta = describir(user)
                antes = foto(user, CAMPOS_USUARIO)
                user.delete()
                registrar(
                    'usuario_eliminado',
                    contexto=contexto,
                    objeto_tipo=tipo,
                    objeto_id=objeto_id,
                    objeto_etiqueta=etiqueta,
                    antes=antes,
                    origen='admin',
                )


@admin.register(SesionActiva)
class SesionActivaAdmin(admin.ModelAdmin):
    """Sesiones abiertas. Borrar una fila libera la cuenta (sesión única).

    Es la salida de emergencia si alguien queda bloqueado y no hay a mano un
    administrador que use /usuarios.
    """

    list_display = ('user', 'dispositivo', 'creada', 'ultima_actividad', 'estado', 'ip')
    search_fields = ('user__email', 'ip')
    readonly_fields = ('user', 'creada', 'ultima_actividad', 'ip', 'user_agent')
    ordering = ('-ultima_actividad',)

    @admin.display(description=_('dispositivo'))
    def dispositivo(self, obj: SesionActiva) -> str:
        return obj.descripcion_dispositivo

    @admin.display(description=_('estado'))
    def estado(self, obj: SesionActiva) -> str:
        return _('Caducada') if obj.vencida else _('Activa')

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def delete_model(self, request, obj):
        self._cerrar(request, [obj])

    def delete_queryset(self, request, queryset):
        self._cerrar(request, list(queryset.select_related('user')))

    def _cerrar(self, request, sesiones):
        """Borrar aquí es un cierre forzado, igual que el botón de /usuarios:
        queda con el mismo evento."""
        contexto = Contexto.de_request(request)
        with transaction.atomic():
            for sesion in sesiones:
                sesion.delete()
                registrar(
                    'sesion_cerrada_por_admin',
                    contexto=contexto,
                    objeto=sesion.user,
                    dispositivo=sesion.descripcion_dispositivo,
                    ip_sesion=sesion.ip,
                    origen='admin',
                )


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    """Solo lectura: sirve para auditar quién pidió restablecer y si lo usó.

    Los tokens no se crean ni editan a mano — se emiten desde el flujo de
    recuperación y solo se guarda su hash, así que aquí no hay nada que escribir.
    """

    list_display = ('user', 'creado', 'expira_en', 'usado_en', 'estado', 'ip_solicitud')
    list_filter = ('creado', 'usado_en')
    search_fields = ('user__email',)
    readonly_fields = (
        'user', 'token_hash', 'creado', 'expira_en', 'usado_en',
        'ip_solicitud', 'ip_uso',
    )
    ordering = ('-creado',)

    @admin.display(description=_('estado'))
    def estado(self, obj: PasswordResetToken) -> str:
        if obj.usado:
            return _('Usado')
        if obj.vencido:
            return _('Vencido')
        return _('Pendiente')

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        # Es una tabla de auditoría: borrar una fila borra la prueba de que
        # alguien pidió (o usó) un restablecimiento.
        return False
