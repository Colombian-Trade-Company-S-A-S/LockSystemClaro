"""H-07: toda salida de información deja huella, también la denegada."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from auditoria.catalogo import Resultado
from televisores.models import BulkSyncJob, PinCodeUsado

from .util import CLAVE, eventos, ultimo

User = get_user_model()


class ExportacionesTests(APITestCase):
    def setUp(self):
        self.operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.consulta = User.objects.create_user(email='consulta@correo.com', password=CLAVE)
        self.client.force_authenticate(user=self.operador)

    def test_deja_quien_que_filtros_y_cuantas_filas(self):
        for passcode in ('A1', 'A2'):
            PinCodeUsado.objects.create(mac_address='AA:BB', passcode=passcode, pin_code='1')

        resp = self.client.get('/api/televisores/exportar-pincodes/?desde=2020-01-01')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        evento = ultimo('exportacion')
        self.assertEqual(evento.resultado, Resultado.EXITO)
        self.assertEqual(evento.usuario_id, self.operador.pk)
        self.assertEqual(evento.detalle['filas'], 2)
        self.assertEqual(evento.detalle['filtros'], {'desde': '2020-01-01'})
        self.assertEqual(evento.detalle['tipo'], 'televisor-exportar-pincodes')
        self.assertTrue(evento.objeto_etiqueta.startswith('pincodes_'))

    def test_las_exportaciones_del_dashboard_tambien(self):
        self.client.get('/api/dashboard/export/usuarios/')
        evento = ultimo('exportacion')
        self.assertEqual(evento.detalle['tipo'], 'export_usuarios')
        self.assertEqual(evento.detalle['filas'], User.objects.count())

    def test_el_csv_de_reportes_tambien(self):
        # El CSV es la única salida que no pasa por `_respuesta_xlsx`.
        for passcode in ('A1', 'A2'):
            PinCodeUsado.objects.create(mac_address='AA:BB', passcode=passcode, pin_code='1')

        resp = self.client.get(
            '/api/reportes/exportar/?origen=pincodes&campos=mac_address,pin_code&formato=csv'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')

        evento = ultimo('exportacion')
        self.assertEqual(evento.usuario_id, self.operador.pk)
        self.assertEqual(evento.detalle['filas'], 2)
        self.assertEqual(evento.detalle['filtros']['formato'], 'csv')
        self.assertEqual(evento.objeto_etiqueta, 'reporte_pincodes.csv')

    def test_el_csv_agrupado_tambien(self):
        PinCodeUsado.objects.create(mac_address='AA:BB', passcode='A1', pin_code='1')
        resp = self.client.get(
            '/api/reportes/exportar/?origen=pincodes&modo=agrupado&dimension=usuario&formato=csv'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(ultimo('exportacion').objeto_etiqueta, 'reporte_pincodes_agrupado.csv')

    def test_una_plantilla_vacia_no_es_salida_de_informacion(self):
        self.client.get('/api/televisores/plantilla-televisores/')
        self.assertEqual(eventos('exportacion').count(), 0)

    def test_exportacion_denegada(self):
        job = BulkSyncJob.objects.create()
        self.client.force_authenticate(user=self.consulta)
        resp = self.client.get(f'/api/televisores/enrolar-estado/{job.pk}/exportar/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        evento = ultimo('exportacion')
        self.assertEqual(evento.resultado, Resultado.DENEGADO)
        self.assertEqual(evento.usuario_id, self.consulta.pk)

    def test_cualquier_otra_accion_denegada(self):
        self.client.force_authenticate(user=self.consulta)
        resp = self.client.post('/api/televisores/', {'mac_address': 'AA:BB:CC:DD:EE:01'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        evento = ultimo('acceso_denegado')
        self.assertEqual(evento.resultado, Resultado.DENEGADO)
        self.assertEqual(evento.detalle['metodo'], 'POST')
        self.assertEqual(evento.detalle['ruta'], '/api/televisores/')

    def test_un_anonimo_no_genera_eventos(self):
        self.client.force_authenticate(user=None)
        self.client.get('/api/televisores/exportar-pincodes/')
        self.assertEqual(eventos('exportacion').count(), 0)
