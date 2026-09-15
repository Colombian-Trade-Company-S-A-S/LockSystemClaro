import ipaddress

from rest_framework import serializers

from integracion.models import ApiKey, separar_ips

NOMBRE_MAX = ApiKey._meta.get_field('nombre').max_length  # 100
IPS_MAX_ENTRADAS = 20
IPS_MAX_CARACTERES = 1000
MENSAJE_NOMBRE = 'Ponle un nombre para identificar al integrador.'


class ApiKeyCrearSerializer(serializers.Serializer):
    """Entrada de creación. Hallazgos EXUS_36: un nombre de más de 100
    caracteres llegaba a la base y reventaba con un 500 sin mensaje, y la lista
    de IPs guardaba cualquier texto."""

    nombre = serializers.CharField(
        max_length=NOMBRE_MAX,
        error_messages={
            'required': MENSAJE_NOMBRE,
            'blank': MENSAJE_NOMBRE,
            'null': MENSAJE_NOMBRE,
            'max_length': f'El nombre no puede superar {NOMBRE_MAX} caracteres.',
        },
    )
    ips_permitidas = serializers.CharField(
        allow_blank=True,
        default='',
        max_length=IPS_MAX_CARACTERES,
        error_messages={
            'max_length': f'La lista de IPs no puede superar {IPS_MAX_CARACTERES} caracteres.',
        },
    )
    expira = serializers.DateField(
        required=False,
        allow_null=True,
        error_messages={'invalid': 'La fecha de caducidad no es válida.'},
    )

    def validate_ips_permitidas(self, value: str) -> str:
        """Cada entrada tiene que ser una IP o un rango CIDR, IPv4 o IPv6.

        `ip_permitida` del modelo ya ignoraba las entradas mal escritas (nunca
        abrían el acceso), pero el usuario creía haber restringido la clave.
        """
        entradas = separar_ips(value)
        if len(entradas) > IPS_MAX_ENTRADAS:
            raise serializers.ValidationError(
                f'Máximo {IPS_MAX_ENTRADAS} IPs o rangos.'
            )
        for entrada in entradas:
            try:
                ipaddress.ip_network(entrada, strict=False)
            except ValueError:
                muestra = entrada if len(entrada) <= 40 else f'{entrada[:40]}…'
                raise serializers.ValidationError(
                    f'«{muestra}» no es una IP ni un rango CIDR válido '
                    '(p. ej. 190.0.0.1 o 192.168.1.0/24).'
                ) from None
        return '\n'.join(entradas)


class ApiKeySerializer(serializers.ModelSerializer):
    """API-key SIN el secreto: es lo que se lista. La clave en claro solo se ve
    una vez, en la respuesta de creación (ver ApiKeyCreadaSerializer)."""

    class Meta:
        model = ApiKey
        fields = [
            'id', 'nombre', 'prefijo', 'activa',
            'ips_permitidas', 'expira',
            'creada', 'ultimo_uso',
        ]
        read_only_fields = fields


class ApiKeyCreadaSerializer(serializers.Serializer):
    """Respuesta de creación: incluye la clave en claro UNA sola vez."""

    id = serializers.UUIDField(read_only=True)
    nombre = serializers.CharField(read_only=True)
    prefijo = serializers.CharField(read_only=True)
    clave = serializers.CharField(read_only=True)
