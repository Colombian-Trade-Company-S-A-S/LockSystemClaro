"""H-05: la migración de datos copia MAC y serial a las sincronizaciones que
ya existían antes del despliegue."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

ANTES = [('televisores', '0015_trazabilidad_syncjob_y_api_key')]
DESPUES = [('televisores', '0016_copiar_identificadores_syncjob')]


class CopiarIdentificadoresSyncJobTests(TransactionTestCase):
    def tearDown(self):
        # Deja la base como la espera el resto de la suite.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_copia_los_del_televisor_y_respeta_los_huerfanos(self):
        executor = MigrationExecutor(connection)
        executor.migrate(ANTES)
        apps = executor.loader.project_state(ANTES).apps
        Televisor = apps.get_model('televisores', 'Televisor')
        SyncJob = apps.get_model('televisores', 'SyncJob')

        tv = Televisor.objects.create(mac_address='AA:BB:CC:DD:EE:01', serial_number='SER001')
        con_tv = SyncJob.objects.create(televisor=tv, inhabilitar=True)
        sin_tv = SyncJob.objects.create(televisor=None, inhabilitar=False)

        executor = MigrationExecutor(connection)
        executor.migrate(DESPUES)
        SyncJob = executor.loader.project_state(DESPUES).apps.get_model('televisores', 'SyncJob')

        con_tv = SyncJob.objects.get(pk=con_tv.pk)
        self.assertEqual(
            (con_tv.mac_address, con_tv.serial_number), ('AA:BB:CC:DD:EE:01', 'SER001')
        )
        sin_tv = SyncJob.objects.get(pk=sin_tv.pk)
        self.assertEqual((sin_tv.mac_address, sin_tv.serial_number), ('', ''))
