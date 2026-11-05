"""Bitácora central de eventos.

Convive con las tablas de auditoría que ya existían (historial de cambios,
sincronizaciones, pines, recuperación de contraseña, sesión activa): no las
reemplaza ni las migra, y cada una sigue sirviendo a su pantalla. Lo que añade
es un solo lugar, con un solo formato, donde buscar cuando la pregunta es
«¿qué pasó con esto?» — incluido lo que antes no dejaba rastro: quién entró,
quién dio permisos, qué información salió.

Las filas solo se escriben (auditoria.services.registrar) y nunca se editan:
el admin es de solo lectura y no hay endpoint de escritura.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .catalogo import ActorTipo, Categoria, Resultado, etiqueta_de


class Evento(models.Model):
    momento = models.DateTimeField('momento', default=timezone.now, editable=False)
    categoria = models.CharField('categoría', max_length=20, choices=Categoria.choices)
    accion = models.CharField('acción', max_length=40)
    resultado = models.CharField(
        'resultado', max_length=10, choices=Resultado.choices, default=Resultado.EXITO
    )

    # --- Actor: quién. Las FK sirven para filtrar; el nombre congelado, para
    # que el evento siga diciendo quién fue aunque la cuenta o la clave cambien.
    actor_tipo = models.CharField('tipo de actor', max_length=10, choices=ActorTipo.choices)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name='usuario',
    )
    api_key = models.ForeignKey(
        'integracion.ApiKey',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name='API key',
    )
    actor_nombre = models.CharField('actor', max_length=255, blank=True, default='')

    # --- Origen: desde dónde. La IP sale de common.net.client_ip (H-01).
    ip = models.GenericIPAddressField('IP', null=True, blank=True)
    navegador = models.CharField('navegador', max_length=300, blank=True, default='')

    # --- Objeto: sobre qué. La etiqueta también va congelada: un televisor
    # borrado sigue identificándose por su serial y su MAC.
    objeto_tipo = models.CharField('tipo de objeto', max_length=20, blank=True, default='')
    objeto_id = models.CharField('id del objeto', max_length=64, blank=True, default='')
    objeto_etiqueta = models.CharField('objeto', max_length=255, blank=True, default='')

    # Antes/después y lo propio de cada acción (motivo, filtros, filas...).
    # Nunca contraseñas, claves ni Códigos Pin.
    detalle = models.JSONField('detalle', default=dict, blank=True)

    # Reservado para correlacionar una acción con sus efectos (H-16). Existe ya
    # para no tener que migrar la tabla cuando se implemente.
    request_id = models.CharField('id de petición', max_length=64, blank=True, default='')

    class Meta:
        verbose_name = 'evento de auditoría'
        verbose_name_plural = 'bitácora de auditoría'
        ordering = ['-momento', '-id']
        indexes = [
            models.Index(fields=['-momento'], name='evento_momento'),
            models.Index(fields=['categoria', '-momento'], name='evento_categoria'),
            models.Index(fields=['accion', '-momento'], name='evento_accion'),
            models.Index(fields=['objeto_tipo', 'objeto_id'], name='evento_objeto'),
            models.Index(fields=['actor_nombre'], name='evento_actor'),
        ]

    def __str__(self) -> str:
        return f'{self.momento:%Y-%m-%d %H:%M} · {self.accion_display} · {self.actor_nombre}'

    @property
    def accion_display(self) -> str:
        return etiqueta_de(self.accion)
