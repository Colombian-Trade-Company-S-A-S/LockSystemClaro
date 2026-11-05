import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from auditoria.catalogo import ActorTipo, Categoria, Resultado
from auditoria.contexto import Contexto
from auditoria.services import diferencias, registrar
from integracion.authentication import ApiKeyUser
from integracion.models import ApiKey

from .util import CHROME, CLAVE

User = get_user_model()


class RegistrarTests(TestCase):
    def test_rechaza_acciones_fuera_del_catalogo(self):
        with self.assertRaises(ValueError):
            registrar('login_ok')

    def test_la_categoria_sale_del_catalogo(self):
        evento = registrar('login_exitoso')
        self.assertEqual(evento.categoria, Categoria.AUTENTICACION)
        self.assertEqual(evento.resultado, Resultado.EXITO)

    def test_sin_contexto_actua_el_sistema(self):
        evento = registrar('sesion_expirada')
        self.assertEqual(evento.actor_tipo, ActorTipo.SISTEMA)
        self.assertEqual(evento.actor_nombre, 'Sistema')

    def test_el_detalle_queda_como_json_y_sin_nulos(self):
        cuando = timezone.now()
        evento = registrar('logout', cuando=cuando, id_x=uuid.uuid4(), motivo=None)
        evento.refresh_from_db()
        self.assertIsInstance(evento.detalle['cuando'], str)
        self.assertIsInstance(evento.detalle['id_x'], str)
        self.assertNotIn('motivo', evento.detalle)

    def test_el_objeto_congela_su_etiqueta(self):
        user = User.objects.create_user(email='ana@correo.com', password=CLAVE)
        evento = registrar('usuario_creado', objeto=user)
        user.email = 'otra@correo.com'
        user.save()
        evento.refresh_from_db()
        self.assertEqual(evento.objeto_tipo, 'usuario')
        self.assertEqual(evento.objeto_id, str(user.pk))
        self.assertEqual(evento.objeto_etiqueta, 'ana@correo.com')

    def test_diferencias_solo_trae_lo_que_cambio(self):
        antes, despues = diferencias({'a': 1, 'b': 2}, {'a': 1, 'b': 3})
        self.assertEqual(antes, {'b': 2})
        self.assertEqual(despues, {'b': 3})


@override_settings(PROXIES_DE_CONFIANZA=1)
class ContextoTests(TestCase):
    def _request(self, user, **extra):
        request = RequestFactory().get(
            '/', HTTP_USER_AGENT=CHROME, REMOTE_ADDR='10.0.0.1', **extra
        )
        request.user = user
        return request

    def test_usuario_del_panel(self):
        user = User.objects.create_user(email='ana@correo.com', password=CLAVE)
        ctx = Contexto.de_request(self._request(user))
        self.assertEqual(ctx.actor_tipo, ActorTipo.USUARIO)
        self.assertEqual(ctx.usuario_id, user.pk)
        self.assertEqual(ctx.actor_nombre, 'ana@correo.com')
        self.assertEqual(ctx.navegador, CHROME)

    def test_api_key(self):
        api_key, _ = ApiKey.generar(nombre='Integrador Uno')
        ctx = Contexto.de_request(self._request(ApiKeyUser(api_key)))
        self.assertEqual(ctx.actor_tipo, ActorTipo.API_KEY)
        self.assertEqual(ctx.api_key_id, api_key.pk)
        self.assertIsNone(ctx.usuario_id)
        self.assertEqual(ctx.actor_nombre, f'Integrador Uno ({api_key.prefijo})')

    def test_anonimo(self):
        ctx = Contexto.de_request(self._request(AnonymousUser()))
        self.assertEqual(ctx.actor_tipo, ActorTipo.ANONIMO)
        self.assertIsNone(ctx.usuario_id)

    def test_la_ip_es_la_de_la_funcion_unica(self):
        # El cliente inventa 6.6.6.6; el proxy añadió al final la real (H-01).
        ctx = Contexto.de_request(
            self._request(AnonymousUser(), HTTP_X_FORWARDED_FOR='6.6.6.6, 190.10.20.30')
        )
        self.assertEqual(ctx.ip, '190.10.20.30')
