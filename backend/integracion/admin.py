from django.contrib import admin
from django.db import transaction

from auditoria.contexto import Contexto
from auditoria.services import diferencias, foto, registrar

from .models import CAMPOS_API_KEY, ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    # La clave nunca se muestra (solo su hash existe): desde el admin se pueden
    # revocar (activa=False) o endurecer, no ver. Para crear una con su clave
    # visible se usa el endpoint de gestión (/api/integracion/api-keys/).
    list_display = ('nombre', 'prefijo', 'activa', 'expira', 'creada', 'ultimo_uso')
    list_filter = ('activa',)
    search_fields = ('nombre', 'prefijo')
    # ips_permitidas y expira SÍ se pueden editar (endurecer una clave
    # existente); el prefijo y el hash no.
    readonly_fields = ('prefijo', 'hash_clave', 'creada', 'ultimo_uso')

    def has_delete_permission(self, request, obj=None) -> bool:
        # Como en la API (hallazgo H-12): una clave se revoca, no se borra, para
        # no perder la constancia de que existió.
        return False

    def save_model(self, request, obj, form, change):
        """Endurecer (o abrir) una clave cambia lo que el integrador puede
        hacer: es un cambio de permisos y queda en la bitácora (H-12)."""
        contexto = Contexto.de_request(request)
        if not change:
            with transaction.atomic():
                super().save_model(request, obj, form, change)
                registrar(
                    'api_key_creada',
                    contexto=contexto,
                    objeto=obj,
                    despues=foto(obj, CAMPOS_API_KEY),
                    origen='admin',
                )
            return
        with transaction.atomic():
            antes = foto(ApiKey.objects.get(pk=obj.pk), CAMPOS_API_KEY)
            super().save_model(request, obj, form, change)
            antes_dif, despues_dif = diferencias(antes, foto(obj, CAMPOS_API_KEY))
            if despues_dif:
                revocada = despues_dif == {'activa': False}
                registrar(
                    'api_key_revocada' if revocada else 'api_key_modificada',
                    contexto=contexto,
                    objeto=obj,
                    antes=antes_dif,
                    despues=despues_dif,
                    origen='admin',
                )
