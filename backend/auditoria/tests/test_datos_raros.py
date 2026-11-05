"""Datos raros que SQLite traga y Postgres no.

Producción es Postgres: `ip` es de tipo inet y `detalle` es jsonb. Un valor que
ahí no cabe (una IP que no es IP, un carácter NUL) revienta la escritura, y
como la huella se escribe dentro de la petición, el usuario recibe un 500 en
vez de su respuesta. Estas pruebas solo muerden de verdad corriendo contra
Postgres; ver la nota de despliegue en DEPLOY.md.
"""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from auditoria.catalogo import Resultado
from auditoria.contexto import Contexto
from auditoria.models import Evento
from auditoria.services import registrar
from common.net import client_ip
from televisores.models import PinCodeUsado

from .util import CLAVE, eventos, ultimo

User = get_user_model()
LOGIN = '/api/auth/token/'


class _Req:
    def __init__(self, **meta):
        self.META = meta


class IpInvalidaTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_client_ip_descarta_lo_que_no_es_una_ip(self):
        # None y no REMOTE_ADDR: esa sería la IP del proxy, no la del cliente.
        req = _Req(HTTP_X_FORWARDED_FOR='no-es-una-ip', REMOTE_ADDR='10.0.0.9')
        self.assertIsNone(client_ip(req))

    @override_settings(PROXIES_DE_CONFIANZA=0)
    def test_remote_addr_vacio_es_none(self):
        self.assertIsNone(client_ip(_Req(REMOTE_ADDR='')))

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_client_ip_acepta_ipv4_e_ipv6(self):
        for ip in ('190.10.20.30', '2800:e2:5b80::1'):
            self.assertEqual(client_ip(_Req(HTTP_X_FORWARDED_FOR=f'8.8.8.8, {ip}')), ip)

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_login_fallido_con_cabecera_basura_no_da_500(self):
        resp = self.client.post(
            LOGIN,
            {'email': 'ana@correo.com', 'password': 'mala'},
            format='json',
            HTTP_X_FORWARDED_FOR='no-es-una-ip',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(ultimo('login_fallido').resultado, Resultado.FALLO)

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_login_exitoso_con_cabecera_basura_no_da_500(self):
        resp = self.client.post(
            LOGIN,
            {'email': 'ana@correo.com', 'password': CLAVE},
            format='json',
            HTTP_X_FORWARDED_FOR='no-es-una-ip',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(eventos('login_exitoso').count(), 1)


class CaracterNulTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.consulta = User.objects.create_user(email='consulta@correo.com', password=CLAVE)

    def test_exportacion_con_nul_en_un_filtro_entrega_y_deja_huella(self):
        PinCodeUsado.objects.create(mac_address='AA:BB', passcode='A1', pin_code='1')
        self.client.force_authenticate(user=self.operador)
        resp = self.client.get('/api/televisores/exportar-pincodes/?otro=a%00b')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(ultimo('exportacion').detalle['filtros'], {'otro': 'ab'})

    def test_denegado_con_nul_sigue_siendo_403(self):
        self.client.force_authenticate(user=self.consulta)
        resp = self.client.post('/api/televisores/?otro=a%00b', {'mac_address': 'AA'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ultimo('acceso_denegado').resultado, Resultado.DENEGADO)


class FiltrosDeLaBitacoraTests(APITestCase):
    def setUp(self):
        admin = User.objects.create_user(
            email='admin@correo.com', password=CLAVE, role='admin'
        )
        self.client.force_authenticate(user=admin)
        registrar('logout', contexto=Contexto.de_usuario(admin))
        Evento.objects.update(ip='190.10.20.30')

    def _contar(self, consulta):
        resp = self.client.get(f'/api/auditoria/eventos/?{consulta}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return resp.data['count']

    def test_ip_valida_encuentra(self):
        self.assertEqual(self._contar('ip=190.10.20.30'), 1)

    def test_ip_invalida_es_sin_resultados_no_500(self):
        self.assertEqual(self._contar('ip=no-es-una-ip'), 0)

    def test_nul_en_los_filtros_no_da_500(self):
        for campo in ('actor', 'objeto', 'accion', 'objeto_id', 'ip'):
            self._contar(f'{campo}=a%00b')


class CuerposRarosTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)

    def test_login_con_nul_es_400(self):
        resp = self.client.post(
            LOGIN, {'email': 'a\u0000@correo.com', 'password': 'x'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_con_cuerpo_de_lista(self):
        self.client.force_authenticate(user=self.ana)
        resp = self.client.post('/api/auth/logout/', [1], format='json')
        self.assertEqual(resp.status_code, status.HTTP_205_RESET_CONTENT)
        self.assertEqual(eventos('logout').count(), 1)


class LoginLimitadoTests(APITestCase):
    """Superar el límite responde 429 y deja huella, venga lo que venga."""

    def setUp(self):
        cache.clear()
        for _ in range(5):
            self.client.post(LOGIN, {'email': 'x@correo.com', 'password': 'mala'}, format='json')

    def _limitado(self, cuerpo):
        return self.client.post(LOGIN, json.dumps(cuerpo), content_type='application/json')

    def test_correo_normal(self):
        self.assertEqual(
            self._limitado({'email': 'x@correo.com', 'password': 'mala'}).status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_correo_con_nul(self):
        resp = self._limitado({'email': 'x\u0000@correo.com', 'password': 'mala'})
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(ultimo('login_fallido').actor_nombre, 'x@correo.com')

    def test_cuerpo_que_no_es_un_objeto(self):
        resp = self._limitado([1, 2, 3])
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_correo_que_no_es_texto(self):
        resp = self._limitado({'email': {'a': 1}, 'password': 'mala'})
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
