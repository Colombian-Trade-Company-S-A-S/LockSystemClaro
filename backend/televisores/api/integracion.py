"""API de integración (máquina-a-máquina), direccionada por SERIAL.

Es el mismo TelevisorViewSet del panel, pero:
  - se accede por `serial_number` en la URL, no por la PK de la base (los
    integradores nos compran por serial y no conocen nuestros ids);
  - se autentica con API-key (no con JWT de usuario).

No se reimplementa nada: se hereda toda la lógica (estados, pines, validación,
exportes…). El "usuario" de la API-key es sintético (ver
integracion/authentication.py); por eso las acciones que auditan quién actuó
guardan usuario vacío + IP (ver `usuario_para_auditoria` en views.py).
"""
from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from integracion.authentication import ApiKeyAuthentication, ApiKeyRateThrottle
from televisores.models import Televisor
from televisores.validadores import SerialInvalido, normalizar_serial

from .serializers import TelevisorSerializer
from .views import TelevisorViewSet, client_ip, usuario_para_auditoria


class IntegracionTelevisorSerializer(TelevisorSerializer):
    """Como el del panel, pero el serial es OBLIGATORIO y único: es la columna
    por la que el integrador direcciona cada televisor."""

    serial_number = serializers.CharField(required=True, allow_blank=False)

    def validate_serial_number(self, value: str) -> str:
        # Mismo formato que el panel; aquí solo cambia que es obligatorio.
        try:
            value = normalizar_serial(value)
        except SerialInvalido as e:
            raise serializers.ValidationError(str(e)) from e
        if not value:
            raise serializers.ValidationError('El serial es obligatorio.')
        qs = Televisor.objects.filter(serial_number__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un televisor con este serial.')
        return value


class IntegracionTelevisorViewSet(TelevisorViewSet):
    # Solo API-key: esta superficie no acepta el JWT del panel.
    authentication_classes = [ApiKeyAuthentication]
    throttle_classes = [ApiKeyRateThrottle]
    serializer_class = IntegracionTelevisorSerializer

    # Se busca por serial. `lookup_url_kwarg='pk'` mantiene el nombre del
    # parámetro que ya usan todas las @action heredadas (que reciben `pk`), así
    # que solo cambia POR QUÉ columna se resuelve, no el resto del código.
    lookup_field = 'serial_number'
    lookup_url_kwarg = 'pk'
    # El serial puede traer letras, dígitos y guiones; se admite cualquier cosa
    # menos la barra (que separa segmentos de la URL).
    lookup_value_regex = '[^/]+'

    # ------------------------------------------------------------------
    # Masivos por JSON (no por Excel): un sistema integrador manda los seriales
    # en el cuerpo, no un archivo. Se sobreescriben las acciones heredadas del
    # panel (que reciben multipart) para esta superficie máquina-a-máquina.
    # ------------------------------------------------------------------
    @action(
        detail=False,
        methods=['post'],
        url_path='enrolar-estado',
        parser_classes=[JSONParser],
    )
    def enrolar_estado(self, request):
        """Actualización masiva de estados por JSON, direccionada por serial.

        Cuerpo (una forma u otra, o ambas combinadas):
            {"inhabilitar": ["S1", "S2"], "habilitar": ["S3"]}
            {"items": [{"serial_number": "S1", "inhabilitar": true}, ...]}

        Fija el estado local de cada serial existente y lanza la sincronización
        masiva al portal en segundo plano. No crea televisores nuevos: los
        seriales que no existan se devuelven en `errores`. Devuelve el id del job
        (para consultar el progreso en `enrolar-estado/{job}/`).
        """
        from televisores.bulk_sync import lanzar_bulk_job
        from televisores.estado_import import procesar_enrolar_estado_serial

        resumen = procesar_enrolar_estado_serial(request.data)
        cambiados = resumen['cambiados']

        # Nada aplicable y solo errores: es una petición inválida (400).
        if not cambiados and resumen['actualizados'] == 0:
            return Response(
                {
                    'detail': 'No se aplicó ningún cambio.',
                    'errores': resumen['errores'],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = (
            lanzar_bulk_job(
                cambiados,
                resumen,
                usuario=usuario_para_auditoria(request),
                ip=client_ip(request),
            )
            if cambiados
            else None
        )
        return Response(
            {
                'job': job.pk if job else None,
                'actualizados': resumen['actualizados'],
                'cambios': len(cambiados),
                'errores': resumen['errores'],
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=False,
        methods=['post'],
        url_path='validar-masivo',
        parser_classes=[JSONParser],
    )
    def validar_masivo(self, request):
        """Validación masiva (dry-run). Cuerpo opcional para acotar por serial:
            {"seriales": ["S1", "S2"]}
        Sin cuerpo (o sin `seriales`), valida TODOS los televisores. Devuelve el
        id del job (progreso en `validar-masivo/{job}/`)."""
        from televisores.bulk_sync import lanzar_validacion_masiva

        seriales = request.data.get('seriales') if isinstance(request.data, dict) else None
        televisores = None
        errores: list[str] = []
        if seriales is not None:
            if not isinstance(seriales, list):
                return Response(
                    {'detail': '"seriales" debe ser una lista.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            limpios = [str(s).strip() for s in seriales if str(s).strip()]
            encontrados: dict[str, Televisor] = {}
            for tv in Televisor.objects.filter(serial_number__in=limpios):
                encontrados.setdefault(tv.serial_number, tv)
            televisores = [encontrados[s] for s in limpios if s in encontrados]
            errores = [f'{s}: no existe un televisor con ese serial.'
                       for s in limpios if s not in encontrados]
            if not televisores:
                return Response(
                    {'detail': 'Ninguno de los seriales existe.', 'errores': errores},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        job = lanzar_validacion_masiva(televisores)
        if job is None:
            return Response(
                {'detail': 'No hay televisores para validar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'job': job.pk, 'total': job.total, 'errores': errores},
            status=status.HTTP_202_ACCEPTED,
        )
