"""H-04 (alta y baja), H-05 (el borrado no destruye el historial) y H-06
(acciones por API-key atribuibles)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from auditoria.catalogo import ActorTipo, Resultado
from integracion.models import ApiKey
from televisores.models import CambioTelevisor, SyncJob, Televisor

from .util import CLAVE, eventos, ultimo

User = get_user_model()

MAC = 'AA:BB:CC:DD:EE:01'


class AltaBajaEdicionTests(APITestCase):
    def setUp(self):
        self.operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.client.force_authenticate(user=self.operador)

    def test_alta_por_el_panel(self):
        resp = self.client.post(
            '/api/televisores/',
            {'mac_address': MAC, 'serial_number': 'SER001'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        evento = ultimo('televisor_creado')
        self.assertEqual(evento.usuario_id, self.operador.pk)
        self.assertEqual(evento.objeto_etiqueta, f'SER001 · {MAC}')
        self.assertEqual(evento.detalle['origen'], 'panel')
        self.assertEqual(evento.detalle['despues']['mac_address'], MAC)

    def test_edicion_registra_solo_lo_que_cambio(self):
        tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001')
        self.client.patch(f'/api/televisores/{tv.pk}/', {'serial_number': 'SER002'}, format='json')

        evento = ultimo('televisor_editado')
        self.assertEqual(evento.detalle['antes'], {'serial_number': 'SER001'})
        self.assertEqual(evento.detalle['despues'], {'serial_number': 'SER002'})
        # El historial de siempre sigue escribiéndose igual.
        self.assertEqual(CambioTelevisor.objects.get().usuario, self.operador)

    def test_guardar_sin_cambios_no_registra(self):
        tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001')
        self.client.patch(f'/api/televisores/{tv.pk}/', {'serial_number': 'SER001'}, format='json')
        self.assertEqual(eventos('televisor_editado').count(), 0)

    def test_la_baja_conserva_el_historial_y_dice_que_se_perdio(self):
        tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001', numero_credito='99')
        job = SyncJob.objects.create(
            televisor=tv, mac_address=MAC, serial_number='SER001', inhabilitar=True
        )

        resp = self.client.delete(f'/api/televisores/{tv.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        # H-05: antes el CASCADE se llevaba esta fila con el televisor.
        job.refresh_from_db()
        self.assertIsNone(job.televisor_id)
        self.assertEqual((job.mac_address, job.serial_number), (MAC, 'SER001'))

        evento = ultimo('televisor_eliminado')
        self.assertEqual(evento.objeto_etiqueta, f'SER001 · {MAC}')
        self.assertEqual(evento.detalle['antes']['numero_credito'], '99')
        self.assertEqual(evento.detalle['historial_conservado']['sincronizaciones'], 1)

    def test_las_sincronizaciones_de_un_televisor_borrado_siguen_identificadas(self):
        tv = Televisor.objects.create(mac_address=MAC, serial_number='SER001')
        SyncJob.objects.create(televisor=tv, mac_address=MAC, serial_number='SER001', inhabilitar=True)
        tv.delete()

        fila = self.client.get('/api/sincronizaciones/').data['results'][0]
        self.assertEqual((fila['mac_address'], fila['serial_number']), (MAC, 'SER001'))


class CargaMasivaTests(APITestCase):
    def setUp(self):
        operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.client.force_authenticate(user=operador)

    def _importar(self, contenido: str):
        archivo = SimpleUploadedFile('televisores.csv', contenido.encode(), 'text/csv')
        return self.client.post(
            '/api/televisores/importar/', {'archivo': archivo}, format='multipart'
        )

    def test_un_evento_por_televisor_y_uno_de_resumen(self):
        Televisor.objects.create(mac_address='AA:BB:CC:DD:EE:03', serial_number='VIEJO')
        resp = self._importar(
            'mac_address,serial_number\n'
            'AA:BB:CC:DD:EE:01,SER01\n'
            'AA:BB:CC:DD:EE:02,SER02\n'
            'AA:BB:CC:DD:EE:03,NUEVO\n'
        )
        self.assertEqual(resp.data['creados'], 2)

        creados = eventos('televisor_creado')
        self.assertEqual(creados.count(), 2)
        self.assertTrue(all(e.detalle['origen'] == 'masivo' for e in creados))
        editado = ultimo('televisor_editado')
        self.assertEqual(editado.detalle['antes'], {'serial_number': 'VIEJO'})

        resumen = ultimo('importacion_masiva')
        self.assertEqual(resumen.detalle['archivo'], 'televisores.csv')
        self.assertEqual((resumen.detalle['creados'], resumen.detalle['actualizados']), (2, 1))

    def test_un_archivo_que_no_aplica_nada_queda_como_intento(self):
        self._importar('serial_number\nS1\n')
        evento = ultimo('importacion_masiva')
        self.assertEqual(evento.resultado, Resultado.FALLO)
        self.assertIn('mac_address', evento.detalle['motivo'])


class AccionesPorApiKeyTests(APITestCase):
    """H-06: lo que hace un integrador queda a nombre de SU clave."""

    def setUp(self):
        self.api_key, clave = ApiKey.generar(nombre='Integrador Uno')
        self.auth = {'HTTP_AUTHORIZATION': f'Api-Key {clave}'}
        self.tv = Televisor.objects.create(mac_address=MAC, serial_number='SERAPI1')

    def test_alta_por_api(self):
        resp = self.client.post(
            '/api/integracion/televisores/',
            {'mac_address': 'AA:BB:CC:DD:EE:09', 'serial_number': 'SERAPI9'},
            format='json',
            **self.auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        evento = ultimo('televisor_creado')
        self.assertEqual(evento.actor_tipo, ActorTipo.API_KEY)
        self.assertEqual(evento.api_key_id, self.api_key.pk)
        self.assertEqual(evento.detalle['origen'], 'api')

    def test_edicion_por_api_guarda_la_clave_en_el_historial(self):
        # Antes esto respondía 500: el usuario sintético de la API-key iba a
        # parar a la FK de usuario del historial.
        resp = self.client.patch(
            '/api/integracion/televisores/SERAPI1/',
            {'numero_credito': '123'},
            format='json',
            **self.auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        cambio = CambioTelevisor.objects.get()
        self.assertIsNone(cambio.usuario_id)
        self.assertEqual(cambio.api_key_id, self.api_key.pk)

    @mock.patch('televisores.sync_runner.threading.Thread')
    def test_cambio_de_estado_por_api(self, _hilo):
        resp = self.client.post(
            '/api/integracion/televisores/SERAPI1/estado/',
            {'inhabilitar': True},
            format='json',
            **self.auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

        job = SyncJob.objects.get()
        self.assertEqual(job.api_key_id, self.api_key.pk)
        self.assertEqual((job.mac_address, job.serial_number), (MAC, 'SERAPI1'))
        self.assertEqual(ultimo('estado_solicitado').api_key_id, self.api_key.pk)

    @mock.patch('televisores.sync_runner.threading.Thread')
    def test_las_pantallas_muestran_la_clave(self, _hilo):
        self.client.post(
            '/api/integracion/televisores/SERAPI1/estado/',
            {'inhabilitar': True},
            format='json',
            **self.auth,
        )
        operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.client.force_authenticate(user=operador)
        fila = self.client.get('/api/sincronizaciones/').data['results'][0]
        self.assertEqual(fila['usuario'], 'API key: Integrador Uno')
