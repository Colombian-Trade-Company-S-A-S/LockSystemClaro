from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from integracion.models import ApiKey

User = get_user_model()


class ApiKeySinBorradoTests(APITestCase):
    """H-12: una API-key se revoca, nunca se borra."""

    def setUp(self):
        admin_user = User.objects.create_superuser(
            email='admin@correo.com', password='ClaveSegura123'
        )
        self.client.force_authenticate(user=admin_user)
        self.api_key, _ = ApiKey.generar(nombre='Integrador')
        self.url = f'/api/integracion/api-keys/{self.api_key.pk}/'

    def test_la_api_no_permite_borrar(self):
        resp = self.client.delete(self.url)
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(ApiKey.objects.filter(pk=self.api_key.pk).exists())

    def test_revocar_la_desactiva_y_la_conserva(self):
        resp = self.client.post(f'{self.url}revocar/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.api_key.refresh_from_db()
        self.assertFalse(self.api_key.activa)

    def test_el_admin_de_django_tampoco_permite_borrar(self):
        self.assertFalse(admin.site._registry[ApiKey].has_delete_permission(None))


@override_settings(PROXIES_DE_CONFIANZA=1)
class ApiKeyListaBlancaTests(APITestCase):
    """H-01: la lista blanca de IPs no se abre con un X-Forwarded-For inventado."""

    url = '/api/integracion/televisores/'

    def setUp(self):
        _, clave = ApiKey.generar(nombre='Integrador', ips_permitidas='190.10.20.30')
        self.auth = f'Api-Key {clave}'

    def test_desde_la_ip_permitida_entra(self):
        resp = self.client.get(
            self.url,
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_FORWARDED_FOR='1.2.3.4, 190.10.20.30',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_poner_la_ip_permitida_en_la_cabecera_no_basta(self):
        # El atacante escribe la IP permitida; el proxy añade al final la suya.
        resp = self.client.get(
            self.url,
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_FORWARDED_FOR='190.10.20.30, 203.0.113.9',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
