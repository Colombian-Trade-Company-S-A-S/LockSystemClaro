from django.contrib import admin
from django.db import transaction

from auditoria.contexto import Contexto
from auditoria.services import describir, diferencias, registrar

from .cambios import foto_completa
from .models import (
    BulkSyncItem,
    BulkSyncJob,
    CambioTelevisor,
    PinCodeUsado,
    SyncJob,
    Televisor,
)


class SoloLecturaAdmin(admin.ModelAdmin):
    """Para las tablas de auditoría: se consultan, no se tocan.

    Las escribe el sistema. Si se pudieran editar o borrar desde aquí,
    dejarían de probar nada.
    """

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Televisor)
class TelevisorAdmin(admin.ModelAdmin):
    """El admin es una vía más de alta, edición y baja (además del panel, la
    carga masiva y la API): también deja su evento en la bitácora (H-04)."""

    list_display = ('mac_address', 'serial_number', 'numero_credito', 'inhabilitado', 'created_at')
    list_filter = ('inhabilitado',)
    search_fields = ('mac_address', 'serial_number', 'numero_credito')

    def save_model(self, request, obj, form, change):
        contexto = Contexto.de_request(request)
        with transaction.atomic():
            antes = foto_completa(Televisor.objects.get(pk=obj.pk)) if change else None
            super().save_model(request, obj, form, change)
            if not change:
                registrar(
                    'televisor_creado',
                    contexto=contexto,
                    objeto=obj,
                    despues=foto_completa(obj),
                    origen='admin',
                )
                return
            antes_dif, despues_dif = diferencias(antes, foto_completa(obj))
            if despues_dif:
                registrar(
                    'televisor_editado',
                    contexto=contexto,
                    objeto=obj,
                    antes=antes_dif,
                    despues=despues_dif,
                    origen='admin',
                )

    def delete_model(self, request, obj):
        self._borrar(request, [obj])

    def delete_queryset(self, request, queryset):
        self._borrar(request, list(queryset))

    def _borrar(self, request, televisores):
        contexto = Contexto.de_request(request)
        with transaction.atomic():
            for tv in televisores:
                tipo, objeto_id, etiqueta = describir(tv)
                antes = foto_completa(tv)
                tv.delete()
                registrar(
                    'televisor_eliminado',
                    contexto=contexto,
                    objeto_tipo=tipo,
                    objeto_id=objeto_id,
                    objeto_etiqueta=etiqueta,
                    antes=antes,
                    origen='admin',
                )


@admin.register(SyncJob)
class SyncJobAdmin(SoloLecturaAdmin):
    list_display = ('id', 'mac_address', 'serial_number', 'inhabilitar', 'estado', 'porcentaje', 'creado')
    list_filter = ('estado', 'inhabilitar')
    search_fields = ('mac_address', 'serial_number')


@admin.register(PinCodeUsado)
class PinCodeUsadoAdmin(SoloLecturaAdmin):
    list_display = ('mac_address', 'passcode', 'pin_code', 'creado')
    search_fields = ('mac_address', 'passcode', 'pin_code')


@admin.register(CambioTelevisor)
class CambioTelevisorAdmin(SoloLecturaAdmin):
    """Historial de cambios: solo lectura, lo escribe el sistema.

    Permitir editarlo desde aquí destruiría su valor como auditoría.
    """

    list_display = (
        'creado', 'serial_number', 'mac_address', 'campo',
        'valor_anterior', 'valor_nuevo', 'origen', 'usuario',
    )
    list_filter = ('campo', 'origen', 'creado')
    search_fields = ('serial_number', 'mac_address', 'numero_credito')
    ordering = ('-creado',)


class BulkSyncItemInline(admin.TabularInline):
    model = BulkSyncItem
    extra = 0

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(BulkSyncJob)
class BulkSyncJobAdmin(SoloLecturaAdmin):
    list_display = ('id', 'modo', 'estado', 'procesados', 'total', 'ok_count', 'error_count', 'creado')
    list_filter = ('estado', 'modo')
    inlines = [BulkSyncItemInline]
