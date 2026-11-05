from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from televisores.models import BulkSyncJob, Televisor

User = get_user_model()

STRONG_PASSWORD = 'ClaveSegura123'


class CancelarLoteHuerfanoTests(APITestCase):
    """H-15: cancelar un lote sin latido respondía 500 (`timezone` sin importar)."""

    def setUp(self):
        operador = User.objects.create_user(
            email='operador@correo.com', password=STRONG_PASSWORD, role='operador'
        )
        self.client.force_authenticate(user=operador)

    def test_cierra_el_lote_sin_latido(self):
        job = BulkSyncJob.objects.create(estado=BulkSyncJob.CORRIENDO, total=1)
        BulkSyncJob.objects.filter(pk=job.pk).update(
            actualizado=timezone.now() - timedelta(hours=1)
        )

        # Normalmente el watchdog lo cierra antes; se anula para entrar en la
        # rama que fallaba (el lote vence entre la pasada del watchdog y esta).
        with mock.patch('televisores.watchdog.marcar_huerfanos'):
            resp = self.client.post(f'/api/televisores/enrolar-estado/{job.pk}/cancelar/')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertEqual(job.estado, BulkSyncJob.CANCELADO)
        self.assertIsNotNone(job.terminado_en)


class ValidacionMasivaAutoriaTests(APITestCase):
    """H-09: la validación masiva guarda quién la lanzó y desde qué IP."""

    def test_guarda_usuario_e_ip(self):
        Televisor.objects.create(mac_address='AA:BB:CC:DD:EE:01')
        consulta = User.objects.create_user(
            email='consulta@correo.com', password=STRONG_PASSWORD
        )
        self.client.force_authenticate(user=consulta)

        # Sin hilo: la prueba no debe salir al portal.
        with mock.patch('televisores.bulk_sync.threading.Thread'):
            resp = self.client.post(
                '/api/televisores/validar-masivo/', REMOTE_ADDR='190.10.20.30'
            )

        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        job = BulkSyncJob.objects.get(pk=resp.data['job'])
        self.assertEqual(job.modo, BulkSyncJob.VALIDACION)
        self.assertEqual(job.usuario, consulta)
        self.assertEqual(job.ip, '190.10.20.30')
