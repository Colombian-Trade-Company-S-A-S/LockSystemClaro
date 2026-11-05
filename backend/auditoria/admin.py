from django.contrib import admin

from .models import Evento


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    """Bitácora central: solo lectura. La escribe el sistema, nunca una persona;
    un registro de auditoría editable no prueba nada."""

    list_display = ('momento', 'categoria', 'accion', 'resultado', 'actor_nombre', 'ip', 'objeto_etiqueta')
    list_filter = ('categoria', 'resultado', 'actor_tipo')
    search_fields = ('actor_nombre', 'objeto_etiqueta', 'objeto_id', 'ip')
    date_hierarchy = 'momento'
    readonly_fields = tuple(f.name for f in Evento._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
