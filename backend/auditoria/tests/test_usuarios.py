"""H-03: el gobierno de permisos deja rastro (API y admin de Django)."""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import Role

from .util import CLAVE, eventos, todo_el_texto, ultimo

User = get_user_model()


class GestionPorApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@correo.com', password=CLAVE)
        self.ana = User.objects.create_user(
            email='ana@correo.com', password=CLAVE, first_name='Ana', last_name='Ruiz'
        )
        self.client.force_authenticate(user=self.admin)

    def _editar(self, **datos):
        return self.client.patch(
            reverse('users:usuario-detalle', args=[self.ana.pk]), datos, format='json'
        )

    def test_alta_con_su_rol_y_sin_contrasena(self):
        resp = self.client.post(
            reverse('users:usuarios'),
            {
                'email': 'nuevo@correo.com',
                'password': 'ClaveDelNuevo789',
                'first_name': 'Nuevo',
                'last_name': 'Operador',
                'role': 'operador',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        evento = ultimo('usuario_creado')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.objeto_etiqueta, 'nuevo@correo.com')
        self.assertEqual(evento.detalle['despues']['role'], 'operador')
        self.assertNotIn('ClaveDelNuevo789', todo_el_texto())
        self.assertNotIn('password', evento.detalle['despues'])

    def test_el_cambio_de_rol_es_un_evento_propio(self):
        self._editar(role='admin')
        evento = ultimo('rol_cambiado')
        self.assertEqual(evento.detalle['antes'], {'role': 'consulta'})
        self.assertEqual(evento.detalle['despues'], {'role': 'admin'})
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertIsNone(ultimo('usuario_actualizado'))

    def test_desactivar(self):
        self._editar(is_active=False)
        self.assertEqual(ultimo('usuario_desactivado').objeto_id, str(self.ana.pk))

    def test_editar_datos_registra_antes_y_despues(self):
        self._editar(last_name='Gómez')
        evento = ultimo('usuario_actualizado')
        self.assertEqual(evento.detalle['antes'], {'last_name': 'Ruiz'})
        self.assertEqual(evento.detalle['despues'], {'last_name': 'Gómez'})

    def test_guardar_sin_cambios_no_registra_nada(self):
        self._editar(first_name='Ana', last_name='Ruiz', role='consulta', is_active=True)
        self.assertEqual(eventos('usuario_actualizado').count(), 0)
        self.assertEqual(eventos('rol_cambiado').count(), 0)

    def test_perfil_propio_y_el_acento_no_cuenta(self):
        self.client.force_authenticate(user=self.ana)
        self.client.patch(reverse('users:me'), {'accent': 'rosa'}, format='json')
        self.assertIsNone(ultimo('perfil_actualizado'))

        self.client.patch(reverse('users:me'), {'first_name': 'Ana María'}, format='json')
        evento = ultimo('perfil_actualizado')
        self.assertEqual(evento.usuario_id, self.ana.pk)
        self.assertEqual(evento.detalle['despues'], {'first_name': 'Ana María'})


class GestionPorAdminDeDjangoTests(TestCase):
    """El admin es la única vía que toca is_staff/is_superuser."""

    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@correo.com', password=CLAVE)
        self.request = RequestFactory().post('/admin/', REMOTE_ADDR='190.10.20.30')
        self.request.user = self.admin
        self.model_admin = admin.site._registry[User]

    def test_alta_desde_el_admin(self):
        nuevo = User(email='nuevo@correo.com')
        nuevo.set_password(CLAVE)
        self.model_admin.save_model(self.request, nuevo, form=None, change=False)
        evento = ultimo('usuario_creado')
        self.assertEqual(evento.detalle['origen'], 'admin')
        self.assertEqual(evento.ip, '190.10.20.30')

    def test_hacer_superusuario_a_alguien(self):
        ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)
        ana.is_superuser = True
        ana.is_staff = True
        ana.role = Role.ADMIN
        self.model_admin.save_model(self.request, ana, form=None, change=True)

        permisos = ultimo('permisos_admin_cambiados')
        self.assertEqual(permisos.detalle['antes'], {'is_staff': False, 'is_superuser': False})
        self.assertEqual(permisos.detalle['despues'], {'is_staff': True, 'is_superuser': True})
        self.assertEqual(ultimo('rol_cambiado').detalle['despues'], {'role': 'admin'})

    def test_borrar_una_cuenta_deja_quien_era(self):
        ana = User.objects.create_user(email='ana@correo.com', password=CLAVE, role=Role.OPERADOR)
        pk = ana.pk
        self.model_admin.delete_model(self.request, ana)

        self.assertFalse(User.objects.filter(pk=pk).exists())
        evento = ultimo('usuario_eliminado')
        self.assertEqual(evento.objeto_id, str(pk))
        self.assertEqual(evento.objeto_etiqueta, 'ana@correo.com')
        self.assertEqual(evento.detalle['antes']['role'], 'operador')
