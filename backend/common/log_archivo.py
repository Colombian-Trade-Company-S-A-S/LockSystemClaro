"""Log de aplicación a archivo, uno por día, con retención (hallazgo H-11).

Hasta ahora el log solo iba a consola: lo que no recogiera la plataforma se
perdía. Este handler lo deja además en disco, en `<directorio>/app-AAAA-MM-DD.log`,
y borra los archivos con más de `retencion_dias`.

Por qué no `TimedRotatingFileHandler`: Gunicorn corre varios workers (procesos)
y ese handler rota RENOMBRANDO el archivo abierto. Con dos procesos, uno renombra
mientras el otro sigue escribiendo en el viejo, y se pierden o se mezclan días.
Aquí no se renombra nada: cada línea va al archivo de SU fecha, abierto en modo
append, y los procesos solo coinciden en añadir al final del mismo archivo.

Es el log técnico de la aplicación, NO una bitácora de auditoría: no se usa
como evidencia ni se mezcla con ella.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

PREFIJO = 'app'


class ArchivoDiarioHandler(logging.Handler):
    def __init__(self, directorio: str, retencion_dias: int):
        super().__init__()
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.retencion_dias = retencion_dias
        self._fecha: datetime.date | None = None
        self._archivo = None

    def emit(self, record: logging.LogRecord) -> None:
        # `handle()` ya toma el lock del handler: aquí no hay carreras entre
        # hilos del mismo proceso.
        try:
            fecha = datetime.date.fromtimestamp(record.created)
            if fecha != self._fecha:
                self._abrir(fecha)
            self._archivo.write(self.format(record) + '\n')
            self._archivo.flush()
        except Exception:  # noqa: BLE001 — un fallo de log nunca tumba la petición
            self.handleError(record)

    def _abrir(self, fecha: datetime.date) -> None:
        if self._archivo is not None:
            self._archivo.close()
        ruta = self.directorio / f'{PREFIJO}-{fecha.isoformat()}.log'
        self._archivo = open(ruta, 'a', encoding='utf-8')
        self._fecha = fecha
        # Se purga al cambiar de día: es cuando aparece un archivo nuevo.
        self._purgar(fecha)

    def _purgar(self, hoy: datetime.date) -> None:
        limite = hoy - datetime.timedelta(days=self.retencion_dias)
        for ruta in self.directorio.glob(f'{PREFIJO}-*.log'):
            try:
                fecha = datetime.date.fromisoformat(ruta.stem[len(PREFIJO) + 1:])
            except ValueError:
                continue  # no es uno de los nuestros
            if fecha < limite:
                try:
                    ruta.unlink(missing_ok=True)
                except OSError:
                    # Otro worker lo tiene abierto (Windows) o ya lo borró:
                    # lo purgará el siguiente cambio de día.
                    pass

    def close(self) -> None:
        self.acquire()
        try:
            if self._archivo is not None:
                self._archivo.close()
                self._archivo = None
                self._fecha = None
        finally:
            self.release()
        super().close()
