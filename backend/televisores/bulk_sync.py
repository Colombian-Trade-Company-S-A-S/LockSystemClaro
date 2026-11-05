"""Ejecución en segundo plano de una sincronización masiva (Enrolar Estado).

Un solo hilo abre UNA sesión del portal (un login) y recorre los televisores del
lote aplicando su estado, actualizando el progreso del BulkSyncJob. El frontend
consulta el avance por polling.
"""
from __future__ import annotations

import logging
import threading

from django.db import connections, transaction
from django.utils import timezone

from auditoria.catalogo import Resultado
from auditoria.contexto import Contexto
from auditoria.services import construir, registrar, registrar_lote

from .models import BulkSyncItem, BulkSyncJob, Televisor
from .portal import open_sync
from .portal.client import PortalError
from .portal.open_client import PortalOpenError
from .portal.proveedor import sesion_proveedor
from .portal.selenium_sync import abrir_sesion, aplicar_en_sesion

logger = logging.getLogger(__name__)


def _registrar_fin(job_id: int, contexto: Contexto | None) -> None:
    """Cierre del lote en la bitácora, a nombre de quien lo lanzó (H-09/H-10).

    Va en el `finally` de cada worker: termine bien, mal o cancelado, el lote
    queda con su final escrito. Un fallo aquí no puede tumbar el hilo.
    """
    try:
        job = BulkSyncJob.objects.get(pk=job_id)
        accion = (
            'validacion_masiva_terminada'
            if job.modo == BulkSyncJob.VALIDACION
            else 'lote_terminado'
        )
        registrar(
            accion,
            contexto=contexto,
            resultado=(
                Resultado.FALLO if job.estado == BulkSyncJob.ERROR else Resultado.EXITO
            ),
            objeto=job,
            estado=job.estado,
            total=job.total,
            procesados=job.procesados,
            ok=job.ok_count,
            errores=job.error_count,
        )
    except Exception:  # noqa: BLE001
        logger.exception('No se pudo registrar el fin del lote %s.', job_id)


def _ejecutar(job_id: int, contexto: Contexto | None = None):
    driver = None
    try:
        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.CORRIENDO, actualizado=timezone.now()
        )
        items = list(
            BulkSyncItem.objects.filter(job_id=job_id).values_list('pk', 'televisor_id')
        )

        driver, wait = abrir_sesion()

        ok = 0
        err = 0
        cancelado = False
        for procesados, (item_pk, tv_id) in enumerate(items, start=1):
            if BulkSyncJob.objects.filter(
                pk=job_id, cancelar_solicitado=True
            ).exists():
                cancelado = True
                break

            try:
                tv = Televisor.objects.get(pk=tv_id)
                res = aplicar_en_sesion(driver, wait, tv)
                if res.ok and res.aplicado:
                    estado_item = BulkSyncItem.OK
                    mensaje = 'Inhabilitado' if tv.inhabilitado else 'Habilitado'
                    ok += 1
                else:
                    estado_item = BulkSyncItem.ERROR
                    mensaje = res.error or 'No se pudo aplicar.'
                    err += 1
            except Exception as e:  # noqa: BLE001
                estado_item = BulkSyncItem.ERROR
                mensaje = f'{type(e).__name__}: {e}'
                err += 1

            BulkSyncItem.objects.filter(pk=item_pk).update(
                estado=estado_item, mensaje=mensaje[:500]
            )
            BulkSyncJob.objects.filter(pk=job_id).update(
                procesados=procesados,
                ok_count=ok,
                error_count=err,
                actualizado=timezone.now(),
            )

        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.CANCELADO if cancelado else BulkSyncJob.TERMINADO,
            terminado_en=timezone.now(),
            actualizado=timezone.now(),
        )
    except Exception as e:  # noqa: BLE001
        # Falló el arranque/login: se marcan los items pendientes como error.
        BulkSyncItem.objects.filter(
            job_id=job_id, estado=BulkSyncItem.PENDIENTE
        ).update(estado=BulkSyncItem.ERROR, mensaje=f'{type(e).__name__}: {e}'[:500])
        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.ERROR,
            error_count=BulkSyncItem.objects.filter(
                job_id=job_id, estado=BulkSyncItem.ERROR
            ).count(),
            terminado_en=timezone.now(),
            actualizado=timezone.now(),
        )
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
        _registrar_fin(job_id, contexto)
        connections.close_all()


def _respaldo_selenium(televisores) -> dict:
    """Aplica por Selenium los televisores que la API no pudo.

    Un solo navegador y un solo login para todos, igual que `_ejecutar`.
    """
    from .portal.selenium_sync import ResultadoSync

    resultados = {}
    driver = None
    try:
        driver, wait = abrir_sesion()
        for tv in televisores:
            res = aplicar_en_sesion(driver, wait, tv)
            res.log.insert(0, 'La API falló; se aplicó con Selenium.')
            resultados[tv.pk] = res
    except Exception as e:  # noqa: BLE001
        # Ni la API ni Selenium: se marcan todos con el fallo del respaldo.
        for tv in televisores:
            if tv.pk not in resultados:
                res = ResultadoSync()
                res.ok = False
                res.error = f'API y Selenium fallaron. Selenium: {type(e).__name__}: {e}'
                resultados[tv.pk] = res
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
    return resultados


def _ejecutar_open(job_id: int, contexto: Contexto | None = None):
    """Igual que `_ejecutar` pero por la Portal API: sin navegador y en lote.

    Selenium necesita un login y una visita por televisor; aquí el bloqueo de
    todo el lote son dos llamadas. Por eso no hay progreso televisor a
    televisor: se marca 0 y luego el total.
    """
    try:
        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.CORRIENDO, actualizado=timezone.now()
        )
        items = list(
            BulkSyncItem.objects.filter(job_id=job_id).values_list('pk', 'televisor_id')
        )
        if BulkSyncJob.objects.filter(pk=job_id, cancelar_solicitado=True).exists():
            BulkSyncJob.objects.filter(pk=job_id).update(
                estado=BulkSyncJob.CANCELADO,
                terminado_en=timezone.now(),
                actualizado=timezone.now(),
            )
            return

        por_tv = {tv_id: item_pk for item_pk, tv_id in items}
        televisores = list(Televisor.objects.filter(pk__in=por_tv.keys()))
        resultados, respaldo = open_sync.aplicar_lote(televisores)

        # Si la API falló para parte del lote, se reintenta esa parte con
        # Selenium: un solo login para todos los que quedaron pendientes.
        if respaldo:
            resultados.update(_respaldo_selenium(respaldo))

        ok = 0
        err = 0
        for tv in televisores:
            res = resultados.get(tv.pk)
            if res is not None and res.ok and res.aplicado:
                estado_item = BulkSyncItem.OK
                mensaje = 'Inhabilitado' if tv.inhabilitado else 'Habilitado'
                ok += 1
            else:
                estado_item = BulkSyncItem.ERROR
                mensaje = (res.error if res else '') or 'No se pudo aplicar.'
                err += 1
            BulkSyncItem.objects.filter(pk=por_tv[tv.pk]).update(
                estado=estado_item, mensaje=mensaje[:500]
            )

        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.TERMINADO,
            procesados=len(televisores),
            ok_count=ok,
            error_count=err,
            terminado_en=timezone.now(),
            actualizado=timezone.now(),
        )
    except Exception as e:  # noqa: BLE001
        BulkSyncItem.objects.filter(
            job_id=job_id, estado=BulkSyncItem.PENDIENTE
        ).update(estado=BulkSyncItem.ERROR, mensaje=f'{type(e).__name__}: {e}'[:500])
        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.ERROR,
            error_count=BulkSyncItem.objects.filter(
                job_id=job_id, estado=BulkSyncItem.ERROR
            ).count(),
            terminado_en=timezone.now(),
            actualizado=timezone.now(),
        )
    finally:
        _registrar_fin(job_id, contexto)
        connections.close_all()


def _ejecutar_validacion(job_id: int, contexto: Contexto | None = None):
    """Validación masiva (dry-run): lee el estado del portal por API y lo compara
    con el estado local. No modifica nada."""
    try:
        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.CORRIENDO, actualizado=timezone.now()
        )
        items = list(
            BulkSyncItem.objects.filter(job_id=job_id).values_list('pk', 'televisor_id')
        )
        ok = 0
        err = 0
        cancelado = False
        # Un solo proveedor para todo el lote: en modo portal eso es UN navegador
        # y UN login para todos los televisores, en vez de uno por equipo.
        with sesion_proveedor() as prov:
            for procesados, (item_pk, tv_id) in enumerate(items, start=1):
                if BulkSyncJob.objects.filter(
                    pk=job_id, cancelar_solicitado=True
                ).exists():
                    cancelado = True
                    break

                try:
                    tv = Televisor.objects.get(pk=tv_id)
                    data = prov.get_status(tv)
                    remoto = data['lockStatus'] == 1
                    local = bool(tv.inhabilitado)
                    coincide = remoto == local
                    estado_item = BulkSyncItem.OK if coincide else BulkSyncItem.ERROR
                    txt = 'Inhabilitado' if remoto else 'Habilitado'
                    txt_local = 'Inhabilitado' if local else 'Habilitado'
                    mensaje = (
                        f'Coinciden ({txt}).'
                        if coincide
                        else f'Portal: {txt} | App: {txt_local}. Conviene sincronizar.'
                    )
                    BulkSyncItem.objects.filter(pk=item_pk).update(
                        estado=estado_item,
                        mensaje=mensaje,
                        remoto_inhabilitado=remoto,
                        local_inhabilitado=local,
                        coincide=coincide,
                    )
                    ok += 1 if coincide else 0
                    err += 0 if coincide else 1
                except (PortalError, PortalOpenError) as e:
                    BulkSyncItem.objects.filter(pk=item_pk).update(
                        estado=BulkSyncItem.ERROR, mensaje=str(e)[:500]
                    )
                    err += 1
                except Exception as e:  # noqa: BLE001
                    BulkSyncItem.objects.filter(pk=item_pk).update(
                        estado=BulkSyncItem.ERROR,
                        mensaje=f'{type(e).__name__}: {e}'[:500],
                    )
                    err += 1

                BulkSyncJob.objects.filter(pk=job_id).update(
                    procesados=procesados,
                    ok_count=ok,
                    error_count=err,
                    actualizado=timezone.now(),
                )

        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.CANCELADO if cancelado else BulkSyncJob.TERMINADO,
            terminado_en=timezone.now(),
            actualizado=timezone.now(),
        )
    except Exception as e:  # noqa: BLE001
        BulkSyncJob.objects.filter(pk=job_id).update(
            estado=BulkSyncJob.ERROR,
            terminado_en=timezone.now(),
            actualizado=timezone.now(),
        )
        print(f'[validacion] error: {e}')
    finally:
        _registrar_fin(job_id, contexto)
        connections.close_all()


def lanzar_validacion_masiva(
    televisores=None, contexto: Contexto | None = None
) -> BulkSyncJob | None:
    """Crea un BulkSyncJob de validación y lanza el hilo.

    Sin `televisores`, valida TODOS (uso del panel). La API de integración puede
    pasar un subconjunto ya resuelto (validación por seriales).

    `contexto` (quién y desde dónde) lo resuelve la vista y viaja hasta el hilo:
    cuando el worker corre ya no hay request de donde sacarlo (hallazgo H-09)."""
    ctx = contexto or Contexto.sistema()
    televisores = list(Televisor.objects.all()) if televisores is None else list(televisores)
    if not televisores:
        return None
    # El hilo arranca DESPUÉS del commit: si arrancara dentro de la
    # transacción, podría buscar el job antes de que exista para él.
    with transaction.atomic():
        job = BulkSyncJob.objects.create(
            modo=BulkSyncJob.VALIDACION,
            total=len(televisores),
            usuario_id=ctx.usuario_id,
            api_key_id=ctx.api_key_id,
            ip=ctx.ip,
        )
        BulkSyncItem.objects.bulk_create([
            BulkSyncItem(
                job=job,
                televisor=tv,
                mac_address=tv.mac_address,
                inhabilitar=tv.inhabilitado,
            )
            for tv in televisores
        ])
        registrar('validacion_masiva_iniciada', contexto=ctx, objeto=job, total=job.total)
    threading.Thread(target=_ejecutar_validacion, args=(job.pk, ctx), daemon=True).start()
    return job


def lanzar_bulk_job(
    cambiados: list[Televisor], resumen: dict, contexto: Contexto | None = None
) -> BulkSyncJob:
    """Crea el BulkSyncJob + items para los TV cambiados y lanza el hilo.

    Además del evento del lote, deja un `estado_solicitado` por televisor: así
    «todo lo que pasó con este televisor» incluye los cambios de estado que le
    llegaron por un archivo, no solo los del botón.
    """
    ctx = contexto or Contexto.sistema()
    with transaction.atomic():
        job = BulkSyncJob.objects.create(
            total=len(cambiados),
            creados=resumen.get('creados', 0),
            actualizados=resumen.get('actualizados', 0),
            errores_import=resumen.get('errores', []),
            usuario_id=ctx.usuario_id,
            api_key_id=ctx.api_key_id,
            ip=ctx.ip,
        )
        BulkSyncItem.objects.bulk_create([
            BulkSyncItem(
                job=job,
                televisor=tv,
                mac_address=tv.mac_address,
                inhabilitar=tv.inhabilitado,
            )
            for tv in cambiados
        ])
        registrar(
            'lote_iniciado',
            contexto=ctx,
            objeto=job,
            total=job.total,
            errores_archivo=len(job.errores_import) or None,
        )
        registrar_lote(
            construir(
                'estado_solicitado',
                contexto=ctx,
                objeto=tv,
                operacion='Inhabilitar' if tv.inhabilitado else 'Habilitar',
                origen='masivo',
                lote=job.pk,
            )
            for tv in cambiados
        )
    runner = _ejecutar_open if open_sync.usa_open() else _ejecutar
    hilo = threading.Thread(target=runner, args=(job.pk, ctx), daemon=True)
    hilo.start()
    return job
