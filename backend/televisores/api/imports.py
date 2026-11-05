"""Parseo e importación de televisores desde CSV/XLSX.

Columnas reconocidas (encabezado, insensible a mayúsculas):
    - mac_address   (obligatoria, identifica el televisor)
    - serial_number (opcional)
    - numero_credito(opcional, solo dígitos)
"""
from __future__ import annotations

import csv
import io

from django.core.exceptions import ValidationError
from django.db import transaction

from auditoria.catalogo import Resultado
from auditoria.contexto import Contexto
from auditoria.services import construir, diferencias, registrar, registrar_lote
from televisores.cambios import foto_completa, registrar_cambios_masivos, snapshot
from televisores.validadores import MacInvalida, normalizar_mac, normalizar_serial
from televisores.models import Televisor

COLUMNAS = ('mac_address', 'serial_number', 'numero_credito')

# Filas por sentencia en bulk_create/bulk_update. Postgres tiene un tope de
# 65535 parámetros por consulta; 500 filas × pocas columnas queda muy por debajo
# y mantiene acotado el uso de memoria.
LOTE = 500


def _normalizar_encabezados(headers: list[str]) -> dict[int, str]:
    """Mapea índice de columna -> nombre de campo reconocido."""
    mapa: dict[int, str] = {}
    for i, h in enumerate(headers):
        clave = (h or '').strip().lower().replace(' ', '_')
        if clave in COLUMNAS:
            mapa[i] = clave
    return mapa


def _filas_csv(data: bytes) -> list[list[str]]:
    texto = data.decode('utf-8-sig', errors='replace')
    return [row for row in csv.reader(io.StringIO(texto))]


def _filas_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    filas: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        filas.append(['' if c is None else str(c) for c in row])
    wb.close()
    return filas


def leer_filas(nombre: str, data: bytes) -> list[list[str]]:
    """Lee un CSV/XLSX y devuelve sus filas como listas de strings."""
    nombre = (nombre or '').lower()
    if nombre.endswith(('.xlsx', '.xls')):
        return _filas_xlsx(data)
    return _filas_csv(data)


def importar_televisores(nombre: str, data: bytes, *, contexto: Contexto) -> dict:
    """Crea/actualiza televisores desde el contenido de un archivo.

    Una consulta para leer los existentes y dos escrituras por lotes, en vez de
    un get_or_create + save por fila: el coste deja de crecer con el número de
    round-trips a la base de datos.

    `contexto` (quién y desde dónde) alimenta el historial de cambios y la
    bitácora central: un evento por televisor creado o modificado y uno con el
    resumen de la carga (hallazgo H-04).

    Devuelve {'creados', 'actualizados', 'errores': [str, ...]}.
    """
    def sin_cambios(errores: list[str]) -> dict:
        # El intento también queda: una carga que no aplicó nada sigue siendo
        # alguien intentando dar de alta equipos.
        registrar(
            'importacion_masiva',
            contexto=contexto,
            resultado=Resultado.FALLO,
            archivo=nombre,
            creados=0,
            actualizados=0,
            errores=len(errores),
            motivo=errores[0] if len(errores) == 1 else None,
        )
        return {'creados': 0, 'actualizados': 0, 'errores': errores}

    filas = leer_filas(nombre, data)

    if not filas:
        return sin_cambios(['El archivo está vacío.'])

    mapa = _normalizar_encabezados(filas[0])
    if 'mac_address' not in mapa.values():
        return sin_cambios(['Falta la columna obligatoria "mac_address".'])

    campos = set(mapa.values())
    errores: list[str] = []

    # Deduplica dentro del archivo conservando el orden de aparición: si una MAC
    # se repite, gana la última fila (mismo criterio que el get_or_create+save
    # secuencial que había antes, pero sin ir a la base de datos por cada una).
    orden: list[str] = []
    deseado: dict[str, dict] = {}

    for n, fila in enumerate(filas[1:], start=2):
        valores = {campo: (fila[i].strip() if i < len(fila) else '') for i, campo in mapa.items()}
        mac = valores.get('mac_address', '').upper()
        if not mac:
            continue  # fila vacía
        try:
            # bulk_create aborta el lote entero ante un error de la base de
            # datos, y full_clean excluye la MAC más abajo: el formato se valida
            # aquí, fila por fila.
            mac = normalizar_mac(mac)
        except MacInvalida as e:
            errores.append(f'Fila {n} ({mac[:20]}): {e}')
            continue
        if mac not in deseado:
            orden.append(mac)
        deseado[mac] = {'fila': n, 'valores': valores}

    if not orden:
        return sin_cambios(errores)

    existentes = {
        tv.mac_address.upper(): tv
        for tv in Televisor.objects.filter(mac_address__in=orden)
    }

    # Foto de los datos actuales antes de tocar nada: es lo que se compara para
    # armar el historial de cambios. Después de mutar los objetos ya no habría
    # forma de saber qué había.
    previos = {mac: snapshot(tv) for mac, tv in existentes.items()}

    nuevos: list[Televisor] = []
    actualizar: list[Televisor] = []

    for mac in orden:
        entrada = deseado[mac]
        valores = entrada['valores']
        tv = existentes.get(mac) or Televisor(mac_address=mac)

        if 'serial_number' in valores:
            tv.serial_number = valores['serial_number']
        if 'numero_credito' in valores:
            tv.numero_credito = valores['numero_credito']

        try:
            # validate_unique=False: la unicidad de la MAC ya la garantiza el
            # dedupe de arriba más el índice único; comprobarla aquí costaría un
            # SELECT por fila, que es justo lo que se quiere evitar.
            tv.full_clean(exclude=['mac_address'], validate_unique=False)
        except ValidationError as exc:
            detalle = '; '.join(f'{k}: {" ".join(v)}' for k, v in exc.message_dict.items())
            errores.append(f'Fila {entrada["fila"]} ({mac}): {detalle}')
            continue

        (actualizar if tv.pk else nuevos).append(tv)

    # Los campos que Televisor.save() normaliza hay que normalizarlos a mano:
    # bulk_create y bulk_update no llaman a save().
    for tv in (*nuevos, *actualizar):
        tv.mac_address = tv.mac_address.strip().upper()
        tv.serial_number = normalizar_serial(tv.serial_number)
        tv.eui64 = (tv.eui64 or '').strip().upper()

    campos_editables = [c for c in ('serial_number', 'numero_credito') if c in campos]

    with transaction.atomic():
        eventos = []
        if nuevos:
            Televisor.objects.bulk_create(nuevos, batch_size=LOTE)
            eventos.extend(
                construir(
                    'televisor_creado',
                    contexto=contexto,
                    objeto=tv,
                    despues=foto_completa(tv),
                    origen='masivo',
                    archivo=nombre,
                )
                for tv in nuevos
            )
        if actualizar and campos_editables:
            Televisor.objects.bulk_update(actualizar, campos_editables, batch_size=LOTE)
            pares = [
                (tv, previos[tv.mac_address.upper()])
                for tv in actualizar
                if tv.mac_address.upper() in previos
            ]
            # Dentro de la transacción: si la escritura de televisores se
            # revierte, el historial no puede quedar afirmando un cambio que no
            # llegó a ocurrir.
            registrar_cambios_masivos(pares=pares, contexto=contexto)
            for tv, antes in pares:
                antes_dif, despues_dif = diferencias(antes, snapshot(tv))
                if despues_dif:
                    eventos.append(construir(
                        'televisor_editado',
                        contexto=contexto,
                        objeto=tv,
                        antes=antes_dif,
                        despues=despues_dif,
                        origen='masivo',
                        archivo=nombre,
                    ))
        registrar_lote(eventos)
        registrar(
            'importacion_masiva',
            contexto=contexto,
            archivo=nombre,
            creados=len(nuevos),
            actualizados=len(actualizar),
            errores=len(errores),
        )

    return {'creados': len(nuevos), 'actualizados': len(actualizar), 'errores': errores}
