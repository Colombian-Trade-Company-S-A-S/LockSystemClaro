"""Pines, lotes y trabajos en segundo plano (H-09, H-10)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from auditoria.catalogo import ActorTipo, Resultado
from auditoria.contexto import Contexto
from televisores import bulk_sync, sync_runner
from televisores.models import BulkSyncJob, PinCodeUsado, SyncJob, Televisor
from televisores.portal.scraper import PortalPasscodeInvalido

from .util import CLAVE, eventos, todo_el_texto, ultimo

User = get_user_model()

MAC = 'AA:BB:CC:DD:EE:01'


@mock.patch('televisores.sync_runner.threading.Thread')
@mock.patch('televisores.api.views.proveedor')
class PinesTests(APITestCase):
    def setUp(self):
        self.consulta = User.objects.create_user(email='consulta@correo.com', password=CLAVE)
        self.client.force_authenticate(user=self.consulta)
        self.tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001', inhabilitado=True)

    def _usar(self, passcode='ACC-77'):
        return self.client.post(
            f'/api/televisores/{self.tv.pk}/pincodes/usar/', {'passcode': passcode}, format='json'
        )

    def test_entrega_sin_guardar_el_pin(self, proveedor, _hilo):
        proveedor.return_value.usar_pincode.return_value = '918273'
        self.assertEqual(self._usar().status_code, status.HTTP_200_OK)

        evento = ultimo('pin_entregado')
        self.assertEqual(evento.usuario_id, self.consulta.pk)
        self.assertEqual(evento.objeto_id, str(self.tv.pk))
        self.assertEqual(evento.detalle['registro'], PinCodeUsado.objects.get().pk)
        self.assertNotIn('918273', todo_el_texto())
        # El pin habilita el televisor: la sincronización queda pedida por él.
        self.assertEqual(ultimo('estado_solicitado').detalle['origen'], 'pin')

    def test_codigo_sin_pin_queda_como_fallo(self, proveedor, _hilo):
        proveedor.return_value.usar_pincode.side_effect = PortalPasscodeInvalido('no')
        self.assertEqual(self._usar().status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ultimo('pin_entregado').resultado, Resultado.FALLO)

    def test_consultar_la_bolsa_de_pines(self, proveedor, _hilo):
        proveedor.return_value.get_pin_codes.return_value = [
            {'passCode': 'A1', 'pinCode': '111111'},
            {'passCode': 'A2', 'pinCode': '222222'},
        ]
        self.client.get(f'/api/televisores/{self.tv.pk}/pincodes/')
        self.assertEqual(ultimo('pines_consultados').detalle['grupos'], 2)
        self.assertNotIn('111111', todo_el_texto())


@mock.patch('televisores.bulk_sync.threading.Thread')
class LotesTests(APITestCase):
    def setUp(self):
        self.operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.client.force_authenticate(user=self.operador)
        self.tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001')

    def test_lote_por_archivo(self, _hilo):
        archivo = SimpleUploadedFile(
            'estados.csv', b'serial_number,estado\nSER001,inhabilitado\n', 'text/csv'
        )
        resp = self.client.post(
            '/api/televisores/enrolar-estado/', {'archivo': archivo}, format='multipart'
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

        lote = ultimo('lote_iniciado')
        self.assertEqual(lote.usuario_id, self.operador.pk)
        self.assertEqual(lote.objeto_id, str(resp.data['job']))
        por_tv = ultimo('estado_solicitado')
        self.assertEqual(por_tv.objeto_id, str(self.tv.pk))
        self.assertEqual(por_tv.detalle['origen'], 'masivo')
        self.assertEqual(por_tv.detalle['lote'], resp.data['job'])

    def test_validacion_masiva_iniciada(self, _hilo):
        resp = self.client.post('/api/televisores/validar-masivo/')
        evento = ultimo('validacion_masiva_iniciada')
        self.assertEqual(evento.objeto_id, str(resp.data['job']))
        self.assertEqual(evento.detalle['total'], 1)

    def test_cancelacion_con_el_estado_del_lote(self, _hilo):
        job = BulkSyncJob.objects.create(estado=BulkSyncJob.CORRIENDO, total=10, procesados=4)
        self.client.post(f'/api/televisores/enrolar-estado/{job.pk}/cancelar/')

        evento = ultimo('lote_cancelado')
        self.assertEqual(evento.usuario_id, self.operador.pk)
        self.assertEqual(evento.detalle['forma'], 'solicitada')
        self.assertEqual(evento.detalle['procesados'], 4)


class FinDeTrabajosTests(APITestCase):
    """El fin de un trabajo queda a nombre de quien lo lanzó: el contexto viaja
    como argumento al hilo, porque ahí ya no hay request."""

    def setUp(self):
        self.operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.ctx = Contexto(
            ActorTipo.USUARIO, self.operador.email, usuario_id=self.operador.pk, ip='190.10.20.30'
        )

    def test_fin_de_un_lote(self):
        job = BulkSyncJob.objects.create(
            estado=BulkSyncJob.TERMINADO, total=3, procesados=3, ok_count=2, error_count=1
        )
        bulk_sync._registrar_fin(job.pk, self.ctx)

        evento = ultimo('lote_terminado')
        self.assertEqual(evento.usuario_id, self.operador.pk)
        self.assertEqual(evento.ip, '190.10.20.30')
        self.assertEqual((evento.detalle['ok'], evento.detalle['errores']), (2, 1))

    def test_fin_de_una_validacion_con_error(self):
        job = BulkSyncJob.objects.create(modo=BulkSyncJob.VALIDACION, estado=BulkSyncJob.ERROR)
        bulk_sync._registrar_fin(job.pk, self.ctx)
        self.assertEqual(ultimo('validacion_masiva_terminada').resultado, Resultado.FALLO)

    def test_fin_de_una_sincronizacion(self):
        tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001')
        job = SyncJob.objects.create(
            televisor=tv, mac_address=MAC, serial_number='SER001', inhabilitar=True,
            estado=SyncJob.ERROR, error='El portal no respondió',
        )
        sync_runner._registrar_fin(job.pk, self.ctx)

        evento = ultimo('sincronizacion_terminada')
        self.assertEqual(evento.resultado, Resultado.FALLO)
        self.assertEqual(evento.objeto_id, str(tv.pk))
        self.assertEqual(evento.detalle['operacion'], 'Inhabilitar')
        self.assertEqual(evento.detalle['error'], 'El portal no respondió')

    def test_un_fallo_al_registrar_no_tumba_el_hilo(self):
        with self.assertLogs('televisores.bulk_sync', level='ERROR'):
            bulk_sync._registrar_fin(999_999, self.ctx)  # no existe
        self.assertEqual(eventos('lote_terminado').count(), 0)
