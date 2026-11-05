"""Regresión (día 19 del plan): las seis tablas de auditoría que ya existían
siguen escribiendo autor e IP después de los cambios de IP (H-01), cascada
(H-05) y credencial (H-06). Si alguna dejara de hacerlo en silencio, el mes de
trabajo habría quitado más de lo que puso.

Todas las peticiones llegan con un X-Forwarded-For falsificado: la IP guardada
tiene que ser la que añadió el proxy, no la que inventó el cliente.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from televisores.models import (
    BulkSyncJob,
    CambioTelevisor,
    PinCodeUsado,
    SyncJob,
    Televisor,
)
from users.models import PasswordResetToken, SesionActiva

from .util import CHROME, CLAVE

User = get_user_model()

FALSA, REAL = '6.6.6.6', '190.10.20.30'
XFF = {'HTTP_X_FORWARDED_FOR': f'{FALSA}, {REAL}'}


@override_settings(PROXIES_DE_CONFIANZA=1)
@mock.patch('televisores.bulk_sync.threading.Thread')
@mock.patch('televisores.sync_runner.threading.Thread')
class TablasDeAuditoriaExistentesTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.operador = User.objects.create_user(
            email='operador@correo.com', password=CLAVE, role='operador'
        )
        self.tv = Televisor.objects.create(mac_address='AA:BB:CC:DD:EE:01', serial_number='SER001')

    def test_sesion_activa(self, *_):
        self.client.post(
            reverse('users:token_obtain_pair'),
            {'email': 'operador@correo.com', 'password': CLAVE},
            format='json',
            HTTP_USER_AGENT=CHROME,
            **XFF,
        )
        self.assertEqual(SesionActiva.objects.get().ip, REAL)

    def test_tokens_de_recuperacion(self, *_):
        self.client.post(
            reverse('users:password_reset'), {'email': 'operador@correo.com'}, format='json', **XFF
        )
        self.assertEqual(PasswordResetToken.objects.get().ip_solicitud, REAL)

    def test_historial_de_cambios(self, *_):
        self.client.force_authenticate(user=self.operador)
        self.client.patch(
            f'/api/televisores/{self.tv.pk}/', {'serial_number': 'SER002'}, format='json', **XFF
        )
        cambio = CambioTelevisor.objects.get()
        self.assertEqual((cambio.usuario, cambio.ip), (self.operador, REAL))

    def test_sincronizaciones_individuales(self, *_):
        self.client.force_authenticate(user=self.operador)
        self.client.post(
            f'/api/televisores/{self.tv.pk}/estado/', {'inhabilitar': True}, format='json', **XFF
        )
        job = SyncJob.objects.get()
        self.assertEqual((job.usuario, job.ip), (self.operador, REAL))

    def test_sincronizaciones_masivas(self, *_):
        self.client.force_authenticate(user=self.operador)
        archivo = SimpleUploadedFile(
            'estados.csv', b'serial_number,estado\nSER001,inhabilitado\n', 'text/csv'
        )
        self.client.post(
            '/api/televisores/enrolar-estado/', {'archivo': archivo}, format='multipart', **XFF
        )
        job = BulkSyncJob.objects.get()
        self.assertEqual((job.usuario, job.ip), (self.operador, REAL))

    @mock.patch('televisores.api.views.proveedor')
    def test_codigos_pin(self, proveedor, *_):
        proveedor.return_value.usar_pincode.return_value = '123456'
        self.client.force_authenticate(user=self.operador)
        self.client.post(
            f'/api/televisores/{self.tv.pk}/pincodes/usar/', {'passcode': 'ACC'}, format='json', **XFF
        )
        pin = PinCodeUsado.objects.get()
        self.assertEqual((pin.usuario, pin.ip), (self.operador, REAL))
