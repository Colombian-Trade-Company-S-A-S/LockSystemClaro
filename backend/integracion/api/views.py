"""Gestión de las API-keys de integración (crear / listar / revocar).

Reservado al Administrador. Vive en el panel: es el único lugar donde se dan de
alta las credenciales que usan los integradores. La clave en claro solo se
devuelve una vez, en la respuesta de creación.
"""
from __future__ import annotations

from datetime import datetime, time

from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from integracion.models import ApiKey
from users.permissions import IsAdminRole

from .serializers import ApiKeyCreadaSerializer, ApiKeyCrearSerializer, ApiKeySerializer


class ApiKeyViewSet(viewsets.ModelViewSet):
    """CRUD de API-keys. Solo el Administrador.

    - list / retrieve: metadatos de las claves (nunca el secreto).
    - create: genera una clave nueva y devuelve la clave en claro UNA vez.
    - revocar (POST detalle): desactiva la clave (no se borra, queda de bitácora).
    - destroy: elimina el registro definitivamente.
    """

    queryset = ApiKey.objects.all()
    serializer_class = ApiKeySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]
    search_fields = ['nombre', 'prefijo']
    ordering_fields = ['nombre', 'creada', 'ultimo_uso']

    def create(self, request, *args, **kwargs):
        entrada = ApiKeyCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        # Endurecimiento opcional: si no se envían, la clave queda sin
        # restricción de IP y sin caducidad (el uso documentado por defecto).
        # La fecha caduca a las 00:00 de ese día, hora local, como antes.
        expira = datos.get('expira')
        api_key, clave = ApiKey.generar(
            nombre=datos['nombre'],
            ips_permitidas=datos['ips_permitidas'],
            expira=timezone.make_aware(datetime.combine(expira, time.min)) if expira else None,
        )
        # La clave en claro SOLO viaja en esta respuesta; después no se puede
        # recuperar (en la base queda su hash). Si se pierde, se genera otra.
        return Response(
            ApiKeyCreadaSerializer(
                {
                    'id': api_key.id,
                    'nombre': api_key.nombre,
                    'prefijo': api_key.prefijo,
                    'clave': clave,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def revocar(self, request, pk=None):
        # Revocar = desactivar (no se borra): así el prefijo no se reutiliza y el
        # registro sirve de bitácora de qué claves existieron.
        api_key = self.get_object()
        api_key.activa = False
        api_key.save(update_fields=['activa'])
        return Response(ApiKeySerializer(api_key).data)
