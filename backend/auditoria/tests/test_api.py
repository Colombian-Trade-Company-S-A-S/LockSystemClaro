"""Consulta de la bitácora: solo Administrador (D-4), filtros y Excel."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from auditoria.catalogo import Resultado
from auditoria.contexto import Contexto
from auditoria.models import Evento
from auditoria.services import registrar
from televisores.models import Televisor

from .util import CLAVE, ultimo

User = get_user_model()

URL = '/api/auditoria/eventos/'


class PermisosTests(APITestCase):
    def test_solo_el_administrador(self):
        for rol in ('consulta', 'operador'):
            user = User.objects.create_user(email=f'{rol}@correo.com', password=CLAVE, role=rol)
            self.client.force_authenticate(user=user)
            for ruta in (URL, f'{URL}exportar/', '/api/auditoria/catalogo/'):
                self.assertEqual(self.client.get(ruta).status_code, status.HTTP_403_FORBIDDEN)

        admin = User.objects.create_user(email='admin@correo.com', password=CLAVE, role='admin')
        self.client.force_authenticate(user=admin)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_200_OK)

    def test_anonimo(self):
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)


class ConsultaTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email='admin@correo.com', password=CLAVE, role='admin')
        self.client.force_authenticate(user=self.admin)
        self.ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)
        self.tv = Televisor.objects.create(mac_address='AA:BB:CC:DD:EE:01', serial_number='SER001')
        de_ana = Contexto.de_usuario(self.ana)

        registrar('login_exitoso', contexto=de_ana, objeto=self.ana)
        registrar('televisor_editado', contexto=de_ana, objeto=self.tv)
        registrar('estado_solicitado', contexto=de_ana, objeto=self.tv)
        registrar('login_fallido', resultado=Resultado.FALLO, objeto=self.ana)
        viejo = registrar('logout', contexto=de_ana, objeto=self.ana)
        Evento.objects.filter(pk=viejo.pk).update(momento=timezone.now() - timedelta(days=40))

    def _ids(self, **params):
        resp = self.client.get(URL, params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return [e['accion'] for e in resp.data['results']]

    def test_todo_lo_que_paso_con_un_televisor(self):
        self.assertEqual(
            self._ids(objeto_tipo='televisor', objeto_id=self.tv.pk),
            ['estado_solicitado', 'televisor_editado'],
        )

    def test_por_categoria_resultado_y_actor(self):
        self.assertEqual(
            set(self._ids(categoria='autenticacion')),
            {'login_exitoso', 'login_fallido', 'logout'},
        )
        self.assertEqual(self._ids(resultado='fallo'), ['login_fallido'])
        self.assertNotIn('login_fallido', self._ids(actor='ana@'))

    def test_por_rango_de_fechas(self):
        hace_una_semana = (timezone.localdate() - timedelta(days=7)).isoformat()
        self.assertNotIn('logout', self._ids(desde=hace_una_semana))

    def test_por_texto_del_objeto(self):
        self.assertEqual(set(self._ids(objeto='SER001')), {'estado_solicitado', 'televisor_editado'})

    def test_la_respuesta_trae_etiquetas_legibles(self):
        evento = self.client.get(URL, {'accion': 'login_exitoso'}).data['results'][0]
        self.assertEqual(evento['accion_display'], 'Inicio de sesión')
        self.assertEqual(evento['categoria_display'], 'Autenticación')
        self.assertEqual(evento['actor_nombre'], 'ana@correo.com')

    def test_exportar_la_bitacora_queda_en_la_bitacora(self):
        resp = self.client.get(f'{URL}exportar/', {'categoria': 'autenticacion'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        evento = ultimo('exportacion')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.detalle['filas'], 3)
        self.assertEqual(evento.detalle['ruta'], f'{URL}exportar/')

    def test_catalogo(self):
        datos = self.client.get('/api/auditoria/catalogo/').data
        accion = next(a for a in datos['acciones'] if a['valor'] == 'login_exitoso')
        self.assertEqual(accion['categoria'], 'autenticacion')
        self.assertIn({'valor': 'denegado', 'etiqueta': 'Denegado'}, datos['resultados'])
