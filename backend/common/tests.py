import datetime
import logging
import shutil
import tempfile
from pathlib import Path

from django.test import RequestFactory, SimpleTestCase, override_settings

from common.log_archivo import ArchivoDiarioHandler
from common.net import client_ip


class ClientIpTests(SimpleTestCase):
    """H-01: la IP que queda en la auditoría no la elige el cliente."""

    def _ip(self, xff=None, remote='10.0.0.1'):
        extra = {'REMOTE_ADDR': remote}
        if xff is not None:
            extra['HTTP_X_FORWARDED_FOR'] = xff
        return client_ip(RequestFactory().get('/', **extra))

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_toma_la_entrada_que_puso_el_proxy(self):
        self.assertEqual(self._ip('190.10.20.30'), '190.10.20.30')

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_ignora_lo_que_mando_el_cliente(self):
        # El cliente manda su propia cabecera y el balanceador añade al final la
        # IP real. Antes se guardaba 1.2.3.4.
        self.assertEqual(self._ip('1.2.3.4, 190.10.20.30'), '190.10.20.30')

    @override_settings(PROXIES_DE_CONFIANZA=2)
    def test_cuenta_los_proxies_desde_la_derecha(self):
        self.assertEqual(self._ip('1.2.3.4, 190.10.20.30, 172.16.0.5'), '190.10.20.30')

    @override_settings(PROXIES_DE_CONFIANZA=2)
    def test_con_menos_entradas_que_proxies_usa_la_primera(self):
        self.assertEqual(self._ip('190.10.20.30'), '190.10.20.30')

    @override_settings(PROXIES_DE_CONFIANZA=1)
    def test_sin_cabecera_usa_la_ip_de_la_conexion(self):
        self.assertEqual(self._ip(), '10.0.0.1')

    @override_settings(PROXIES_DE_CONFIANZA=0)
    def test_sin_proxies_ignora_la_cabecera(self):
        self.assertEqual(self._ip('1.2.3.4'), '10.0.0.1')


class ArchivoDiarioHandlerTests(SimpleTestCase):
    """H-11: el log se guarda en un archivo por día y se purga lo vencido."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _handler(self, retencion_dias=30):
        handler = ArchivoDiarioHandler(str(self.dir), retencion_dias=retencion_dias)
        # Se cierra antes de borrar la carpeta (addCleanup corre al revés).
        self.addCleanup(handler.close)
        return handler

    @staticmethod
    def _registro(fecha, mensaje):
        registro = logging.LogRecord('prueba', logging.INFO, __file__, 1, mensaje, None, None)
        registro.created = datetime.datetime.combine(fecha, datetime.time(12)).timestamp()
        return registro

    def _leer(self, nombre):
        return (self.dir / nombre).read_text(encoding='utf-8')

    def test_cada_linea_va_al_archivo_de_su_dia(self):
        handler = self._handler()
        handler.handle(self._registro(datetime.date(2026, 10, 21), 'ayer'))
        handler.handle(self._registro(datetime.date(2026, 10, 22), 'hoy'))
        handler.handle(self._registro(datetime.date(2026, 10, 22), 'hoy otra vez'))

        self.assertEqual(self._leer('app-2026-10-21.log'), 'ayer\n')
        self.assertEqual(self._leer('app-2026-10-22.log'), 'hoy\nhoy otra vez\n')

    def test_al_cambiar_de_dia_borra_solo_los_vencidos(self):
        vencido = self.dir / 'app-2026-09-01.log'
        vigente = self.dir / 'app-2026-10-01.log'
        ajeno = self.dir / 'otro.log'
        for ruta in (vencido, vigente, ajeno):
            ruta.write_text('x', encoding='utf-8')

        self._handler(retencion_dias=30).handle(
            self._registro(datetime.date(2026, 10, 22), 'hoy')
        )

        self.assertFalse(vencido.exists())
        self.assertTrue(vigente.exists())
        self.assertTrue(ajeno.exists())
