"""H-02: ingresos, fallos, cierres, expiración y cierre forzado."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from auditoria.catalogo import ActorTipo, Resultado
from users.models import PasswordResetToken, SesionActiva
from users.services import sesion_vigente

from .util import CHROME, CLAVE, EQUIPO, eventos, todo_el_texto, ultimo

User = get_user_model()

EDGE = CHROME + ' Edg/120.0.0.0'


class LoginTests(APITestCase):
    def setUp(self):
        cache.clear()  # el throttle de login (5/min) no debe cruzarse entre tests
        self.ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)

    def _login(self, email, password=CLAVE, navegador=CHROME):
        return self.client.post(
            reverse('users:token_obtain_pair'),
            {'email': email, 'password': password},
            format='json',
            HTTP_USER_AGENT=navegador,
            REMOTE_ADDR=EQUIPO,
        )

    def test_ingreso_exitoso(self):
        self.assertEqual(self._login('ana@correo.com').status_code, status.HTTP_200_OK)

        evento = ultimo('login_exitoso')
        self.assertEqual(evento.actor_tipo, ActorTipo.USUARIO)
        self.assertEqual(evento.usuario_id, self.ana.pk)
        self.assertEqual(evento.objeto_id, str(self.ana.pk))
        self.assertEqual(evento.ip, EQUIPO)
        self.assertEqual(evento.detalle['dispositivo'], 'Chrome en Windows')
        self.assertEqual(evento.detalle['sesion'], str(SesionActiva.objects.get().pk))

    def test_contrasena_incorrecta(self):
        resp = self._login('ana@correo.com', password='incorrecta-123')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        evento = ultimo('login_fallido')
        self.assertEqual(evento.resultado, Resultado.FALLO)
        self.assertEqual(evento.actor_tipo, ActorTipo.ANONIMO)
        self.assertEqual(evento.actor_nombre, 'ana@correo.com')
        self.assertEqual(evento.objeto_id, str(self.ana.pk))
        self.assertEqual(evento.detalle['motivo'], 'contraseña incorrecta')
        # El motivo va a la bitácora, no a la respuesta.
        self.assertNotIn('contraseña incorrecta', str(resp.data))

    def test_cuenta_inexistente_guarda_el_correo_tecleado(self):
        self._login('nadie@correo.com')
        evento = ultimo('login_fallido')
        self.assertEqual(evento.actor_nombre, 'nadie@correo.com')
        self.assertEqual(evento.objeto_id, '')
        self.assertEqual(evento.detalle['motivo'], 'cuenta inexistente')

    def test_cuenta_inactiva(self):
        self.ana.is_active = False
        self.ana.save()
        self._login('ana@correo.com')
        self.assertEqual(ultimo('login_fallido').detalle['motivo'], 'cuenta inactiva')

    def test_sesion_ocupada(self):
        self._login('ana@correo.com')
        resp = self._login('ana@correo.com', navegador=EDGE)
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

        evento = ultimo('login_fallido')
        # Las credenciales eran buenas: el actor es la propia cuenta.
        self.assertEqual(evento.actor_tipo, ActorTipo.USUARIO)
        self.assertEqual(evento.usuario_id, self.ana.pk)
        self.assertEqual(evento.detalle['motivo'], 'la cuenta ya tiene una sesión abierta')

    def test_superar_el_limite_de_intentos_queda_registrado(self):
        for _ in range(6):
            resp = self._login('ana@correo.com', password='incorrecta-123')
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn('demasiados intentos', ultimo('login_fallido').detalle['motivo'])

    def test_ninguna_contrasena_entra_en_la_bitacora(self):
        self._login('ana@correo.com', password='incorrecta-123')
        self._login('ana@correo.com')
        texto = todo_el_texto()
        self.assertNotIn('incorrecta-123', texto)
        self.assertNotIn(CLAVE, texto)


class CierreDeSesionTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)

    def _entrar(self) -> str:
        resp = self.client.post(
            reverse('users:token_obtain_pair'),
            {'email': 'ana@correo.com', 'password': CLAVE},
            format='json',
            HTTP_USER_AGENT=CHROME,
            REMOTE_ADDR=EQUIPO,
        )
        return resp.data['access']

    def _salir(self, token, **datos):
        return self.client.post(
            reverse('users:logout'),
            datos,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
            REMOTE_ADDR=EQUIPO,
        )

    def test_cierre_de_sesion(self):
        self._salir(self._entrar())
        evento = ultimo('logout')
        self.assertEqual(evento.usuario_id, self.ana.pk)
        self.assertEqual(evento.objeto_id, str(self.ana.pk))

    def test_cierre_por_inactividad_en_el_navegador(self):
        self._salir(self._entrar(), motivo='inactividad')
        self.assertIsNone(ultimo('logout'))
        self.assertEqual(ultimo('sesion_expirada').detalle['detectada_por'], 'navegador')

    def test_expiracion_detectada_por_el_servidor_se_registra_una_vez(self):
        self._entrar()
        SesionActiva.objects.update(ultima_actividad=timezone.now() - timedelta(hours=2))

        self.assertIsNone(sesion_vigente(self.ana))
        self.assertIsNone(sesion_vigente(self.ana))

        self.assertEqual(eventos('sesion_expirada').count(), 1)
        evento = ultimo('sesion_expirada')
        self.assertEqual(evento.actor_tipo, ActorTipo.SISTEMA)
        self.assertEqual(evento.objeto_id, str(self.ana.pk))
        self.assertEqual(evento.detalle['detectada_por'], 'servidor')
        self.assertEqual(evento.detalle['ip_sesion'], EQUIPO)

    def test_cierre_forzado_por_un_administrador(self):
        self._entrar()
        admin = User.objects.create_superuser(email='admin@correo.com', password=CLAVE)
        self.client.force_authenticate(user=admin)
        resp = self.client.post(
            reverse('users:usuario-cerrar-sesion', args=[self.ana.pk]), REMOTE_ADDR=EQUIPO
        )
        self.assertTrue(resp.data['cerrada'])

        evento = ultimo('sesion_cerrada_por_admin')
        self.assertEqual(evento.usuario_id, admin.pk)
        self.assertEqual(evento.objeto_id, str(self.ana.pk))


class ContrasenaTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.ana = User.objects.create_user(email='ana@correo.com', password=CLAVE)

    def test_cambio_de_contrasena(self):
        self.client.force_authenticate(user=self.ana)
        resp = self.client.post(
            reverse('users:change_password'),
            {'current_password': CLAVE, 'new_password': 'OtraClaveSegura456'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(ultimo('password_cambiado').resultado, Resultado.EXITO)
        self.assertNotIn('OtraClaveSegura456', todo_el_texto())

    def test_contrasena_actual_incorrecta(self):
        self.client.force_authenticate(user=self.ana)
        resp = self.client.post(
            reverse('users:change_password'),
            {'current_password': 'no-es-esta', 'new_password': 'OtraClaveSegura456'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        evento = ultimo('password_cambiado')
        self.assertEqual(evento.resultado, Resultado.FALLO)
        self.assertEqual(evento.detalle['motivo'], 'contraseña actual incorrecta')

    def test_recuperacion_solicitada_con_y_sin_cuenta(self):
        url = reverse('users:password_reset')
        self.client.post(url, {'email': 'ana@correo.com'}, format='json')
        self.client.post(url, {'email': 'nadie@correo.com'}, format='json')

        con_cuenta, sin_cuenta = eventos('password_reset_solicitado')
        self.assertEqual(con_cuenta.resultado, Resultado.EXITO)
        self.assertEqual(con_cuenta.objeto_id, str(self.ana.pk))
        self.assertEqual(sin_cuenta.resultado, Resultado.FALLO)
        self.assertEqual(sin_cuenta.actor_nombre, 'nadie@correo.com')

    def test_recuperacion_completada(self):
        _, token = PasswordResetToken.emitir(user=self.ana)
        resp = self.client.post(
            reverse('users:password_reset_confirm'),
            {'token': token, 'new_password': 'OtraClaveSegura456'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        evento = ultimo('password_reset_completado')
        self.assertEqual(evento.resultado, Resultado.EXITO)
        self.assertEqual(evento.usuario_id, self.ana.pk)
        self.assertNotIn(token, todo_el_texto())

    def test_enlace_invalido(self):
        self.client.post(
            reverse('users:password_reset_confirm'),
            {'token': 'inventado', 'new_password': 'OtraClaveSegura456'},
            format='json',
        )
        self.assertEqual(ultimo('password_reset_completado').resultado, Resultado.FALLO)
