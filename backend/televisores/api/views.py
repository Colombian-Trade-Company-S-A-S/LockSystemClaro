from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from televisores.cambios import registrar_cambios, snapshot
from televisores.models import Televisor
from users.permissions import CanOperate
from televisores.portal.client import (
    PortalDispositivoNoExiste,
    PortalError,
)
from televisores.portal.proveedor import modo as modo_portal
from televisores.portal.proveedor import proveedor
from televisores.portal.scraper import (
    PortalCapacidadNoDisponible,
    PortalPasscodeInvalido,
)

from .imports import importar_televisores


def client_ip(request) -> str | None:
    """IP del cliente, considerando un posible proxy inverso (X-Forwarded-For)."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _eui64_o_vacio(tv) -> str:
    """EUI-64 del televisor, o '' si la MAC no permite derivarlo.

    En modo portal la MAC basta para operar (el portal busca por MAC), así que
    una MAC rara no debe tumbar la respuesta: solo deja el campo vacío.
    """
    try:
        return tv.eui64_portal
    except ValueError:
        return ''


def usuario_para_auditoria(request):
    """Usuario real para guardar como FK de auditoría, o None.

    Las peticiones de la API de integración traen un usuario sintético de
    API-key (pk=None) que no es una fila de la base: no puede guardarse como
    llave foránea. En ese caso se audita con usuario vacío + la IP. Para el panel
    (JWT) devuelve el usuario autenticado normal."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or getattr(user, 'pk', None) is None:
        return None
    return user
from .serializers import (
    BulkSyncJobSerializer,
    PinCodeUsadoSerializer,
    SyncJobSerializer,
    TelevisorSerializer,
)


class TelevisorViewSet(viewsets.ModelViewSet):
    """CRUD de televisores + acciones contra el portal WhaleTV.

    - list / retrieve / create / update / destroy estándar.
    - `?search=` busca por MAC, serial o número de crédito (SearchFilter global).
    - `importar/`        carga masiva desde CSV/XLSX.
    - `estado-portal/`   (GET)  lee el estado real del dispositivo en el portal.
    - `habilitar/`       (POST) desbloquea el dispositivo en el portal (unlock).
    - `inhabilitar/`     (POST) marca inhabilitado localmente (ver nota).
    """

    queryset = Televisor.objects.all()
    serializer_class = TelevisorSerializer
    search_fields = ['mac_address', 'serial_number', 'numero_credito']
    ordering_fields = ['mac_address', 'serial_number', 'created_at']

    # Acciones de escritura/gestión reservadas a Operador y Administrador.
    # El resto (consultas, validación, pines, reportes) queda para cualquier
    # usuario autenticado, incluido el rol Consulta.
    OPERATOR_ACTIONS = frozenset({
        'create',
        'update',
        'partial_update',
        'destroy',
        'importar',                  # Enrolar Televisores (masivo)
        'enrolar_estado',            # Enrolar Estado (masivo)
        'enrolar_estado_cancelar',   # Cancelar sincronización masiva
        'enrolar_estado_exportar',   # Exportar sincronización masiva a Excel
        'estado',                    # Habilitar / Inhabilitar (sincroniza al portal)
    })

    def get_permissions(self):
        if self.action in self.OPERATOR_ACTIONS:
            return [permissions.IsAuthenticated(), CanOperate()]
        return [permissions.IsAuthenticated()]

    def update(self, request, *args, **kwargs):
        """Edición individual, dejando constancia en el historial de cambios.

        Los valores previos se leen ANTES de guardar; después ya no hay forma de
        saber qué había. Se registra fuera del serializer para que la auditoría
        no dependa de por dónde entren los datos.
        """
        antes = snapshot(self.get_object())
        respuesta = super().update(request, *args, **kwargs)

        televisor = self.get_object()
        registrar_cambios(
            televisor=televisor,
            antes=antes,
            usuario=request.user,
            ip=client_ip(request),
        )
        return respuesta

    @action(
        detail=False,
        methods=['post'],
        url_path='importar',
        parser_classes=[MultiPartParser, FormParser],
    )
    def importar(self, request):
        archivo = request.FILES.get('archivo')
        if not archivo:
            return Response(
                {'detail': 'Debes adjuntar un archivo en el campo "archivo".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resultado = importar_televisores(
            archivo.name,
            archivo.read(),
            usuario=request.user,
            ip=client_ip(request),
        )
        return Response(resultado, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Integración con el portal WhaleTV (Device Lock API)
    # ------------------------------------------------------------------
    @staticmethod
    def _respuesta_mac_invalida() -> Response:
        """400 cuando la MAC guardada no permite derivar el EUI-64 (p. ej. datos
        de prueba con 'XX'). No es un fallo del servidor: es un dato inválido."""
        return Response(
            {
                'detail': (
                    'La dirección MAC del televisor no es válida para consultar el '
                    'portal (no se puede derivar el EUI-64). Corrige la MAC o define '
                    'el EUI-64 manualmente.'
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _leer_estado_portal(self, tv: Televisor) -> Response | dict:
        try:
            data = proveedor().get_status(tv)
        except ValueError:
            return self._respuesta_mac_invalida()
        except PortalDispositivoNoExiste as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except PortalError as e:
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        return {
            'eui64': _eui64_o_vacio(tv),
            'lock_status': data['lockStatus'],       # 0=desbloqueado, 1=bloqueado
            # En modo portal payment/clear no existen: el portal no los publica.
            'payment_status': data['paymentStatus'],  # 0=en progreso, 1=completado
            'clear_status': data['clearStatus'],      # 0=normal, 1=limpiando
            'inhabilitado_portal': data['lockStatus'] == 1,
            'modo': modo_portal(),
        }

    @action(detail=True, methods=['get'], url_path='estado-portal')
    def estado_portal(self, request, pk=None):
        resultado = self._leer_estado_portal(self.get_object())
        if isinstance(resultado, Response):
            return resultado
        return Response(resultado)

    @action(detail=True, methods=['get'])
    def validar(self, request, pk=None):
        """Valida (dry-run) el estado del TV: lee el portal y lo compara con el
        estado local, sin modificar nada."""
        tv = self.get_object()
        resultado = self._leer_estado_portal(tv)
        if isinstance(resultado, Response):
            return resultado

        remoto = bool(resultado['inhabilitado_portal'])
        local = bool(tv.inhabilitado)
        coincide = remoto == local
        txt = 'Inhabilitado' if remoto else 'Habilitado'
        txt_local = 'Inhabilitado' if local else 'Habilitado'
        mensaje = (
            f'El televisor está {txt} en el portal, igual que en la app. '
            'No hay nada que sincronizar.'
            if coincide
            else f'El televisor está {txt} en el portal, pero {txt_local} en la app. '
            'Conviene sincronizar para que coincidan.'
        )
        return Response({
            'coincide': coincide,
            'remoto_inhabilitado': remoto,
            'local_inhabilitado': local,
            'mensaje': mensaje,
        })

    @action(detail=False, methods=['post'], url_path='validar-masivo')
    def validar_masivo(self, request):
        """Lanza una validación masiva (dry-run) de todos los televisores."""
        from televisores.bulk_sync import lanzar_validacion_masiva

        job = lanzar_validacion_masiva()
        if job is None:
            return Response(
                {'detail': 'No hay televisores para validar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'job': job.pk, 'total': job.total}, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=False, methods=['get'], url_path='jobs-activos')
    def jobs_activos(self, request):
        """Todo lo que está corriendo ahora mismo: syncs individuales y lotes.

        Existe para que un operador que cerró la pestaña (o llega desde otro
        equipo) pueda ver qué hay en marcha y cancelarlo. Antes, si perdías la
        pantalla del progreso no había forma de volver a encontrar el job.

        `vivo` distingue lo que realmente avanza de lo que se quedó sin hilo
        (ver televisores/watchdog.py); el frontend lo usa para ofrecer
        descartarlo en vez de esperar.
        """
        from televisores.models import BulkSyncJob, SyncJob
        from televisores.watchdog import esta_vivo, marcar_huerfanos

        marcar_huerfanos()

        activos = [SyncJob.PENDIENTE, SyncJob.CORRIENDO]
        individuales = [
            {
                'job': j.pk,
                'televisor_id': j.televisor_id,
                'mac_address': j.televisor.mac_address,
                'serial_number': j.televisor.serial_number,
                'inhabilitar': j.inhabilitar,
                'estado': j.estado,
                'porcentaje': j.porcentaje,
                'creado': j.creado,
                'actualizado': j.actualizado,
                'vivo': esta_vivo(j),
                'usuario': j.usuario.get_full_name() if j.usuario else '',
            }
            for j in SyncJob.objects.filter(estado__in=activos)
            .select_related('televisor', 'usuario')
            .order_by('-creado')[:50]
        ]

        lotes = [
            {
                'job': b.pk,
                'modo': b.modo,  # 'sync' | 'validacion'
                'estado': b.estado,
                'total': b.total,
                'procesados': b.procesados,
                'ok_count': b.ok_count,
                'error_count': b.error_count,
                'porcentaje': b.porcentaje,
                'cancelar_solicitado': b.cancelar_solicitado,
                'creado': b.creado,
                'actualizado': b.actualizado,
                'vivo': esta_vivo(b),
                'usuario': b.usuario.get_full_name() if b.usuario else '',
            }
            for b in BulkSyncJob.objects.filter(
                estado__in=[BulkSyncJob.PENDIENTE, BulkSyncJob.CORRIENDO]
            )
            .select_related('usuario')
            .order_by('-creado')[:50]
        ]

        return Response({'individuales': individuales, 'lotes': lotes})

    @action(
        detail=False,
        methods=['get'],
        url_path=r'validar-masivo/(?P<job_id>[0-9]+)',
    )
    def validar_masivo_status(self, request, job_id=None):
        """Progreso/resultado de una validación masiva (polling)."""
        from televisores.models import BulkSyncJob
        from televisores.watchdog import marcar_huerfanos

        # Cierra los lotes cuyo hilo murió; si no, este polling no acabaría.
        marcar_huerfanos()

        try:
            job = BulkSyncJob.objects.prefetch_related('items').get(pk=job_id)
        except BulkSyncJob.DoesNotExist:
            return Response(
                {'detail': 'Job no encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(BulkSyncJobSerializer(job).data)

    @action(
        detail=False,
        methods=['post'],
        url_path=r'validar-masivo/(?P<job_id>[0-9]+)/cancelar',
    )
    def validar_masivo_cancelar(self, request, job_id=None):
        return self._cancelar_bulk_job(job_id)

    @action(
        detail=False,
        methods=['get'],
        url_path=r'validar-masivo/(?P<job_id>[0-9]+)/exportar',
    )
    def validar_masivo_exportar(self, request, job_id=None):
        return self._exportar_bulk_job(job_id)

    @action(detail=True, methods=['get'])
    def pincodes(self, request, pk=None):
        """Grupos de Pin Code disponibles del dispositivo (passCode + pinCode)."""
        tv = self.get_object()
        try:
            grupos = proveedor().get_pin_codes(tv)
        except ValueError:
            return self._respuesta_mac_invalida()
        except PortalCapacidadNoDisponible as e:
            # Modo portal: la bolsa de códigos no es consultable. Se responde 501
            # (no implementado en esta configuración) y NO una lista vacía, que
            # se confundiría con "el dispositivo se quedó sin códigos".
            return Response(
                {
                    'detail': (
                        f'{e} Usa POST pincodes/usar/ con el Código de Acceso que '
                        'muestra el televisor.'
                    ),
                    'modo': modo_portal(),
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        except PortalDispositivoNoExiste as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except PortalError as e:
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(
            {'eui64': _eui64_o_vacio(tv), 'grupos': grupos, 'modo': modo_portal()}
        )

    @action(detail=True, methods=['post'], url_path='pincodes/usar')
    def pincode_usar(self, request, pk=None):
        """Obtiene el Código Pin para un Código de Acceso, lo marca como usado en
        el portal y lo registra en la bitácora (aparece en /pincodes).

        Además deja el televisor Habilitado y lanza la sincronización con el
        portal: el Código Pin desbloquea el equipo, así que la consola y el
        portal tienen que reflejarlo (hallazgo EXUS_36). Devuelve el id del job
        para hacer polling, igual que `estado`.
        """
        from televisores.models import PinCodeUsado
        from televisores.sync_runner import lanzar_sync_job

        tv = self.get_object()
        passcode = str(request.data.get('passcode', '')).strip()
        if not passcode:
            return Response(
                {'detail': 'Debes enviar "passcode".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # El proveedor resuelve el passcode y ya lo deja marcado como usado:
        # por API con `marcar_pincodes_usados`, por portal al generarlo.
        try:
            pin_code = proveedor().usar_pincode(tv, passcode)
        except ValueError:
            return self._respuesta_mac_invalida()
        except PortalPasscodeInvalido:
            return Response(
                {'detail': 'No hay un Código Pin disponible para ese Código de Acceso.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PortalDispositivoNoExiste as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        except PortalError as e:
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        usuario = usuario_para_auditoria(request)
        ip = client_ip(request)
        registro = PinCodeUsado.objects.create(
            televisor=tv,
            mac_address=tv.mac_address,
            passcode=passcode,
            pin_code=pin_code,
            usuario=usuario,
            ip=ip,
        )

        # Se sincroniza aunque la consola ya dijera Habilitado: si el portal
        # quedó bloqueado (una sync anterior que falló), el televisor se
        # volvería a bloquear después de desbloquearlo con el pin. Queda en
        # Sincronizaciones como una habilitación más, con usuario e IP.
        tv.inhabilitado = False
        tv.save(update_fields=['inhabilitado'])
        job = lanzar_sync_job(tv, False, usuario=usuario, ip=ip)

        return Response({
            'passcode': passcode,
            'pin_code': pin_code,
            'creado': registro.creado,
            'inhabilitado': tv.inhabilitado,
            'job': job.pk,
        })

    @action(detail=True, methods=['post'])
    def estado(self, request, pk=None):
        """Guarda el estado local (habilitado/inhabilitado) y lanza la sync al
        portal en segundo plano. Devuelve el id del job para hacer polling.

        Body: {"inhabilitar": true|false}
        """
        from televisores.sync_runner import lanzar_sync_job

        tv = self.get_object()
        inhabilitar = bool(request.data.get('inhabilitar'))

        # El estado local es la fuente de verdad; se guarda de inmediato (whaletv).
        tv.inhabilitado = inhabilitar
        tv.save(update_fields=['inhabilitado'])

        job = lanzar_sync_job(
            tv, inhabilitar, usuario=usuario_para_auditoria(request), ip=client_ip(request)
        )
        return Response(
            {
                'job': job.pk,
                'estado': job.estado,
                'inhabilitado': tv.inhabilitado,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=True,
        methods=['get'],
        url_path=r'sync/(?P<job_id>[0-9]+)',
    )
    def sync_status(self, request, pk=None, job_id=None):
        """Estado/progreso de un SyncJob (para polling desde el frontend)."""
        from televisores.models import SyncJob
        from televisores.watchdog import marcar_huerfanos

        # Antes de responder, cierra los jobs cuyo hilo murió (reinicio del
        # servidor): si no, este polling no terminaría nunca.
        marcar_huerfanos()

        # get_object() resuelve el televisor por la columna que use el viewset
        # (PK en el panel, serial en integración).
        tv = self.get_object()
        job = SyncJob.objects.filter(pk=job_id, televisor=tv).first()
        if job is None:
            return Response(
                {'detail': 'Job no encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        return Response({
            'job': job.pk,
            'estado': job.estado,
            'porcentaje': job.porcentaje,
            'finalizado': job.finalizado,
            'error': job.error,
            'inhabilitar': job.inhabilitar,
        })

    @action(
        detail=True,
        methods=['post'],
        url_path=r'sync/(?P<job_id>[0-9]+)/cancelar',
    )
    def sync_cancelar(self, request, pk=None, job_id=None):
        """Descarta un SyncJob que se quedó colgado.

        No mata nada: un sync individual es una sola operación de Selenium que
        no se puede interrumpir a mitad. Por eso solo se descartan los jobs SIN
        LATIDO (su hilo ya no existe). Si el job sigue trabajando responde 409,
        para no dejarlo 'cancelado' y que luego reviva al terminar el hilo.
        """
        from televisores.models import SyncJob
        from televisores.watchdog import MENSAJE, esta_vivo, marcar_huerfanos

        marcar_huerfanos()

        tv = self.get_object()
        job = SyncJob.objects.filter(pk=job_id, televisor=tv).first()
        if job is None:
            return Response(
                {'detail': 'Job no encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        if job.finalizado:
            return Response({
                'job': job.pk,
                'estado': job.estado,
                'porcentaje': job.porcentaje,
                'finalizado': True,
                'error': job.error,
                'inhabilitar': job.inhabilitar,
            })
        if esta_vivo(job):
            return Response(
                {
                    'detail': (
                        'La sincronización sigue en curso; no se puede cancelar a '
                        'mitad. Espera a que termine o vuelve a intentarlo si deja '
                        'de avanzar.'
                    ),
                    'estado': job.estado,
                    'porcentaje': job.porcentaje,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Sin latido: el hilo murió. Se cierra para desbloquear al que espera.
        from django.utils import timezone

        ahora = timezone.now()
        SyncJob.objects.filter(pk=job.pk).update(
            estado=SyncJob.ERROR,
            error=MENSAJE,
            porcentaje=100,
            terminado_en=ahora,
            actualizado=ahora,
        )
        job.refresh_from_db()
        return Response({
            'job': job.pk,
            'estado': job.estado,
            'porcentaje': job.porcentaje,
            'finalizado': job.finalizado,
            'error': job.error,
            'inhabilitar': job.inhabilitar,
        })

    @action(detail=True, methods=['get'])
    def historial(self, request, pk=None):
        """Histórico de cambios de estado (SyncJobs) del televisor."""
        from televisores.watchdog import marcar_huerfanos

        marcar_huerfanos()
        tv = self.get_object()
        jobs = tv.sync_jobs.all()[:50]
        return Response(SyncJobSerializer(jobs, many=True).data)

    # ------------------------------------------------------------------
    # Registros del televisor (sincronizaciones y códigos pin usados)
    # ------------------------------------------------------------------
    @action(detail=True, methods=['get'])
    def registros(self, request, pk=None):
        """Contadores para la sección 'Registros' del detalle."""
        from televisores.models import BulkSyncItem, BulkSyncJob, PinCodeUsado, SyncJob

        tv = self.get_object()
        sinc = (
            SyncJob.objects.filter(televisor=tv).count()
            + BulkSyncItem.objects.filter(
                televisor=tv, job__modo=BulkSyncJob.SYNC
            ).count()
        )
        pins = PinCodeUsado.objects.filter(televisor=tv).count()
        return Response({'sincronizaciones': sinc, 'pincodes': pins})

    @action(detail=True, methods=['get'])
    def sincronizaciones(self, request, pk=None):
        """Historial de sincronizaciones de ESTE televisor (paginado)."""
        from .registros import _fila, qs_sincronizaciones

        qs = qs_sincronizaciones(televisor=self.get_object())
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([_fila(r) for r in page])

    @action(detail=True, methods=['get'], url_path='pincodes-usados')
    def pincodes_usados(self, request, pk=None):
        """Códigos Pin usados de ESTE televisor (paginado)."""
        from televisores.models import PinCodeUsado

        tv = self.get_object()
        qs = PinCodeUsado.objects.filter(televisor=tv)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(
            PinCodeUsadoSerializer(page, many=True).data
        )

    @action(detail=True, methods=['get'], url_path='exportar-sincronizaciones')
    def exportar_sincronizaciones_tv(self, request, pk=None):
        """Excel con TODAS las sincronizaciones de ESTE televisor (sin paginar)."""
        from televisores.api.exports import exportar_sincronizaciones

        return exportar_sincronizaciones(televisor=self.get_object())

    @action(detail=True, methods=['get'], url_path='exportar-pincodes')
    def exportar_pincodes_tv(self, request, pk=None):
        """Excel con TODOS los Códigos Pin usados de ESTE televisor."""
        from televisores.api.exports import exportar_pincodes

        return exportar_pincodes(televisor=self.get_object())

    # ------------------------------------------------------------------
    # Enrolar Estado: cambio de estado masivo + sincronización al portal
    # ------------------------------------------------------------------
    @action(
        detail=False,
        methods=['post'],
        url_path='enrolar-estado',
        parser_classes=[MultiPartParser, FormParser],
    )
    def enrolar_estado(self, request):
        """Importa estados (habilitado/inhabilitado) desde CSV/XLSX, fija el
        estado local y lanza la sincronización masiva al portal en 2º plano.

        Campo multipart: `archivo`. Devuelve el resumen + el id del job masivo.
        """
        from televisores.bulk_sync import lanzar_bulk_job
        from televisores.estado_import import procesar_enrolar_estado

        archivo = request.FILES.get('archivo')
        if not archivo:
            return Response(
                {'detail': 'Debes adjuntar un archivo en el campo "archivo".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resumen = procesar_enrolar_estado(archivo.name, archivo.read())
        cambiados = resumen['cambiados']

        job = (
            lanzar_bulk_job(
                cambiados, resumen, usuario=request.user, ip=client_ip(request)
            )
            if cambiados
            else None
        )
        return Response(
            {
                'job': job.pk if job else None,
                'creados': resumen['creados'],
                'actualizados': resumen['actualizados'],
                'cambios': len(cambiados),
                'errores': resumen['errores'],
            },
            status=status.HTTP_202_ACCEPTED,
        )

    # ------------------------------------------------------------------
    # Exportaciones a Excel (.xlsx)
    # ------------------------------------------------------------------
    @action(detail=False, methods=['get'], url_path='exportar-sincronizaciones')
    def exportar_sincronizaciones(self, request):
        from televisores.api.exports import exportar_sincronizaciones
        return exportar_sincronizaciones(
            request.query_params.get('desde'),
            request.query_params.get('hasta'),
        )

    @action(detail=False, methods=['get'], url_path='exportar-pincodes')
    def exportar_pincodes(self, request):
        from televisores.api.exports import exportar_pincodes
        return exportar_pincodes(
            request.query_params.get('desde'),
            request.query_params.get('hasta'),
        )

    @action(detail=False, methods=['get'], url_path='plantilla-televisores')
    def plantilla_televisores(self, request):
        from televisores.api.exports import plantilla_televisores
        return plantilla_televisores()

    @action(detail=False, methods=['get'], url_path='plantilla-estados')
    def plantilla_estados(self, request):
        from televisores.api.exports import plantilla_estados
        return plantilla_estados()

    @action(
        detail=False,
        methods=['get'],
        url_path=r'enrolar-estado/(?P<job_id>[0-9]+)',
    )
    def enrolar_estado_status(self, request, job_id=None):
        """Progreso de una sincronización masiva (para polling)."""
        from televisores.models import BulkSyncJob
        from televisores.watchdog import marcar_huerfanos

        # Cierra los lotes cuyo hilo murió; si no, este polling no acabaría.
        marcar_huerfanos()

        try:
            job = BulkSyncJob.objects.prefetch_related('items').get(pk=job_id)
        except BulkSyncJob.DoesNotExist:
            return Response(
                {'detail': 'Job no encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(BulkSyncJobSerializer(job).data)

    @action(
        detail=False,
        methods=['post'],
        url_path=r'enrolar-estado/(?P<job_id>[0-9]+)/cancelar',
    )
    def enrolar_estado_cancelar(self, request, job_id=None):
        return self._cancelar_bulk_job(job_id)

    @action(
        detail=False,
        methods=['get'],
        url_path=r'enrolar-estado/(?P<job_id>[0-9]+)/exportar',
    )
    def enrolar_estado_exportar(self, request, job_id=None):
        return self._exportar_bulk_job(job_id)

    def _exportar_bulk_job(self, job_id):
        from televisores.api.exports import exportar_bulk_job
        from televisores.models import BulkSyncJob

        try:
            job = BulkSyncJob.objects.prefetch_related('items').get(pk=job_id)
        except BulkSyncJob.DoesNotExist:
            return Response(
                {'detail': 'Job no encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        return exportar_bulk_job(job)

    def _cancelar_bulk_job(self, job_id):
        """Marca un BulkSyncJob (sync o validación) para que el hilo en
        segundo plano lo detenga en el próximo televisor que revise.

        Si el lote ya no late, no hay hilo que atienda la petición: en ese caso
        se cierra directamente, que si no quedaría 'corriendo' para siempre.
        """
        from televisores.models import BulkSyncJob
        from televisores.watchdog import esta_vivo, marcar_huerfanos

        marcar_huerfanos()

        try:
            job = BulkSyncJob.objects.get(pk=job_id)
        except BulkSyncJob.DoesNotExist:
            return Response(
                {'detail': 'Job no encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        if not job.finalizado:
            if esta_vivo(job):
                # Hay hilo: cancelación cooperativa (se detiene en el siguiente).
                job.cancelar_solicitado = True
                job.save(update_fields=['cancelar_solicitado'])
            else:
                job.estado = BulkSyncJob.CANCELADO
                job.terminado_en = timezone.now()
                job.save(update_fields=['estado', 'terminado_en', 'actualizado'])
        return Response(BulkSyncJobSerializer(job).data)
