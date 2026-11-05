from rest_framework import serializers

from auditoria.models import Evento
from users.models import describir_user_agent


class EventoSerializer(serializers.ModelSerializer):
    categoria_display = serializers.CharField(source='get_categoria_display', read_only=True)
    accion_display = serializers.CharField(read_only=True)
    resultado_display = serializers.CharField(source='get_resultado_display', read_only=True)
    actor_tipo_display = serializers.CharField(source='get_actor_tipo_display', read_only=True)
    # 'Chrome en Windows' se lee mejor que la cadena User-Agent entera, que va
    # en `navegador` para quien la necesite.
    dispositivo = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            'id',
            'momento',
            'categoria',
            'categoria_display',
            'accion',
            'accion_display',
            'resultado',
            'resultado_display',
            'actor_tipo',
            'actor_tipo_display',
            'actor_nombre',
            'usuario',
            'api_key',
            'ip',
            'navegador',
            'dispositivo',
            'objeto_tipo',
            'objeto_id',
            'objeto_etiqueta',
            'detalle',
        ]
        read_only_fields = fields

    def get_dispositivo(self, obj) -> str:
        return describir_user_agent(obj.navegador) if obj.navegador else ''
