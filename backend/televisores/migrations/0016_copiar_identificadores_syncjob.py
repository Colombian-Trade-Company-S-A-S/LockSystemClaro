"""Copia la MAC y el serial de cada televisor a sus sincronizaciones ya hechas.

Hasta la 0015 un SyncJob solo apuntaba al televisor y se borraba con él. Ahora
sobrevive al borrado (SET_NULL), pero las filas viejas no tienen su copia de
los identificadores: sin esto, si mañana se borra un televisor, su historial
anterior a este despliegue quedaría sin decir de qué equipo era.

Es una sola UPDATE con subconsulta, no una por fila. No se puede deshacer (al
revertir, la columna simplemente desaparece con la 0015), por eso la vuelta es
un no-op.
"""
from django.db import migrations
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce


def copiar_identificadores(apps, schema_editor):
    SyncJob = apps.get_model('televisores', 'SyncJob')
    Televisor = apps.get_model('televisores', 'Televisor')

    del_televisor = Televisor.objects.filter(pk=OuterRef('televisor_id'))
    SyncJob.objects.filter(televisor__isnull=False).update(
        mac_address=Coalesce(Subquery(del_televisor.values('mac_address')[:1]), Value('')),
        serial_number=Coalesce(
            Subquery(del_televisor.values('serial_number')[:1]), Value('')
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('televisores', '0015_trazabilidad_syncjob_y_api_key'),
    ]

    operations = [
        migrations.RunPython(copiar_identificadores, migrations.RunPython.noop),
    ]
