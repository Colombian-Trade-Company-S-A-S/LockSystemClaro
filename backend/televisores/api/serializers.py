from rest_framework import serializers

from televisores.models import (
    BulkSyncItem,
    BulkSyncJob,
    CambioTelevisor,
    PinCodeUsado,
    SyncJob,
    Televisor,
)
from televisores.validadores import (
    MacInvalida,
    SerialInvalido,
    normalizar_mac,
    normalizar_serial,
)


class TelevisorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Televisor
        fields = [
            'id',
            'mac_address',
            'serial_number',
            'numero_credito',
            'inhabilitado',
            'eui64',
            'created_at',
        ]
        # El estado y las fechas no se editan desde el CRUD del televisor.
        read_only_fields = ['id', 'inhabilitado', 'created_at']
        extra_kwargs = {
            'eui64': {'required': False},
        }

    def validate_serial_number(self, value: str) -> str:
        """Formato del número de serie: solo letras y números.

        Aplica igual al alta y a la edición (el hallazgo EXUS salió por las dos
        vías). Un serial heredado que no cumpla —quedaron algunos de pruebas—
        bloquea el guardado hasta corregirlo, que es justo lo que se busca.
        """
        try:
            value = normalizar_serial(value)
        except SerialInvalido as e:
            raise serializers.ValidationError(str(e)) from e

        if not value:
            return value
        # Unicidad: dos televisores con el mismo serial romperían la carga
        # masiva por serial y la API de integración, que direccionan por él.
        qs = Televisor.objects.filter(serial_number__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                'Ya existe un televisor con este número de serie.'
            )
        return value

    def validate_mac_address(self, value: str) -> str:
        try:
            value = normalizar_mac(value)
        except MacInvalida as e:
            raise serializers.ValidationError(str(e)) from e
        if not value:
            raise serializers.ValidationError('La dirección MAC es obligatoria.')
        # Unicidad (ignorando el propio registro al editar).
        qs = Televisor.objects.filter(mac_address=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un televisor con esta MAC.')
        return value


class CambioTelevisorSerializer(serializers.ModelSerializer):
    """Fila del historial de cambios, lista para pintar en la tabla."""

    campo_display = serializers.CharField(source='get_campo_display', read_only=True)
    origen_display = serializers.CharField(source='get_origen_display', read_only=True)
    usuario = serializers.SerializerMethodField()

    class Meta:
        model = CambioTelevisor
        fields = [
            'id',
            'creado',
            'mac_address',
            'serial_number',
            'numero_credito',
            'campo',
            'campo_display',
            'valor_anterior',
            'valor_nuevo',
            'origen',
            'origen_display',
            'usuario',
        ]

    def get_usuario(self, obj) -> str:
        """Nombre completo, o el correo si no lo tiene, o '—' si se borró."""
        if not obj.usuario_id:
            return '—'
        return obj.usuario.get_full_name() or obj.usuario.email


class PinCodeUsadoSerializer(serializers.ModelSerializer):
    # El serial vive en el televisor asociado (SET_NULL): si el equipo se borró
    # o el pin no quedó ligado, sale vacío.
    serial_number = serializers.SerializerMethodField()

    class Meta:
        model = PinCodeUsado
        fields = ['id', 'mac_address', 'serial_number', 'passcode', 'pin_code', 'creado']

    def get_serial_number(self, obj) -> str:
        return obj.televisor.serial_number if obj.televisor_id else ''


class SyncJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncJob
        fields = [
            'id',
            'inhabilitar',
            'estado',
            'porcentaje',
            'error',
            'creado',
            'terminado_en',
        ]


class BulkSyncItemSerializer(serializers.ModelSerializer):
    # El lote se arma a partir de un archivo direccionado por serial, así que
    # el resultado se lee mejor por serial que por MAC. Sale del televisor
    # relacionado (el ítem solo guarda la MAC); vacío si el TV fue eliminado.
    serial_number = serializers.CharField(
        source='televisor.serial_number', read_only=True, default=''
    )

    class Meta:
        model = BulkSyncItem
        fields = [
            'id',
            'mac_address',
            'serial_number',
            'inhabilitar',
            'estado',
            'mensaje',
            'remoto_inhabilitado',
            'local_inhabilitado',
            'coincide',
        ]


class BulkSyncJobSerializer(serializers.ModelSerializer):
    porcentaje = serializers.IntegerField(read_only=True)
    finalizado = serializers.BooleanField(read_only=True)
    items = BulkSyncItemSerializer(many=True, read_only=True)

    class Meta:
        model = BulkSyncJob
        fields = [
            'id',
            'modo',
            'estado',
            'total',
            'procesados',
            'ok_count',
            'error_count',
            'porcentaje',
            'finalizado',
            'creados',
            'actualizados',
            'errores_import',
            'items',
            'creado',
            'terminado_en',
        ]
