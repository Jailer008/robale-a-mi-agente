"""reiniciar_demo(): vuelve la base de la demo al estado inicial controlado, sin carreras.

- Base sintética controlada (`<db>_base.db`, o DB_BASE_PATH): esquema, histórico de pagos del CSV,
  cero decisiones, cero eventos, cero pagos simulados. Si falta o fue alterada, se reconstruye.
- Copia con la API de backup de SQLite (nunca copiando archivos de una base viva en modo WAL).
- Antes de restaurar se respalda la base viva en `respaldos/` (evidencia de los ensayos).
- Puerta de concurrencia: espera a que terminen las solicitudes en curso (decidir, reanudar,
  reevaluar) y retiene las nuevas mientras dura el reinicio; si no terminan a tiempo, no toca nada.
- Se conservan reglas.yaml y la clave de firma: la cadena nueva arranca desde GENESIS y se sigue
  firmando con la misma clave. El endpoint HTTP que lo invoque es de Dev 3.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cerebro.db import BaseDatos, leer_pagos, verificar_pagos
from cerebro.dinero import cents_a_decimal

if TYPE_CHECKING:
    from cerebro import Cerebro


class ReinicioOcupado(RuntimeError):
    """Hay solicitudes en curso que no terminaron a tiempo (o ya hay otro reinicio): no se tocó nada."""


class Puerta:
    """Muchas operaciones a la vez, o un reinicio exclusivo. Dentro de un proceso."""

    def __init__(self) -> None:
        self._condicion = threading.Condition()
        self._activas = 0
        self._cerrada = False

    @contextmanager
    def operacion(self) -> Iterator[None]:
        with self._condicion:
            while self._cerrada:
                self._condicion.wait()
            self._activas += 1
        try:
            yield
        finally:
            with self._condicion:
                self._activas -= 1
                self._condicion.notify_all()

    @contextmanager
    def exclusiva(self, timeout_s: float) -> Iterator[None]:
        with self._condicion:
            if self._cerrada:
                raise ReinicioOcupado("Ya hay un reinicio en curso")
            self._cerrada = True
            limite = time.monotonic() + timeout_s
            while self._activas:
                restante = limite - time.monotonic()
                if restante <= 0:
                    self._cerrada = False
                    self._condicion.notify_all()
                    raise ReinicioOcupado(f"Hay {self._activas} solicitudes en curso: reintente el reinicio")
                self._condicion.wait(restante)
        try:
            yield
        finally:
            with self._condicion:
                self._cerrada = False
                self._condicion.notify_all()


def copiar_base(origen: Path, destino: Path) -> None:
    """Copia consistente con sqlite3.Connection.backup (segura con WAL y con lectores)."""
    fuente = sqlite3.connect(origen, timeout=30)
    try:
        objetivo = sqlite3.connect(destino, timeout=30)
        try:
            fuente.backup(objetivo, sleep=0.05)
            objetivo.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            objetivo.close()
    finally:
        fuente.close()


def _base_valida(ruta: Path, historico_csv: Path) -> bool:
    if not ruta.is_file():
        return False
    try:
        con = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error:
        return False
    try:
        vacias = (con.execute("SELECT COUNT(*) FROM decision_log").fetchone()[0] == 0
                  and con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0] == 0)
        secreto = con.execute("SELECT COUNT(*) FROM metadatos WHERE clave = 'secreto_cuentas'").fetchone()[0] == 1
        simulados = con.execute("SELECT COUNT(*) FROM pagos WHERE origen = 'simulado'").fetchone()[0]
        return vacias and secreto and simulados == 0 and not verificar_pagos(con, historico_csv)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _construir_base(ruta: Path, cerebro: Cerebro) -> None:
    """Rehace la base en un archivo temporal y la vuelca con la API de backup: no hace falta borrar
    `ruta` (en Windows podría estar abierta por un lector)."""
    temporal = ruta.with_name(f"{ruta.stem}.construyendo{ruta.suffix}")
    for sufijo in ("", "-wal", "-shm"):
        Path(f"{temporal}{sufijo}").unlink(missing_ok=True)
    BaseDatos(temporal).inicializar(cerebro.historico_csv, cerebro._reglas_actuales())
    copiar_base(temporal, ruta)
    for sufijo in ("", "-wal", "-shm"):
        try:
            Path(f"{temporal}{sufijo}").unlink(missing_ok=True)
        except OSError:
            pass                                               # se reutiliza o se pisa en el próximo intento


def reiniciar(cerebro: Cerebro, admin: str, *, timeout_s: float = 30.0, respaldar: bool = True) -> dict[str, Any]:
    if not isinstance(admin, str) or not admin.strip():
        raise ValueError("Falta el administrador")
    admin = admin.strip()
    if not cerebro.administradores or admin not in cerebro.administradores:
        raise PermissionError(f"'{admin}' no es un administrador autorizado (CEREBRO_ADMINS)")

    with cerebro._puerta.exclusiva(timeout_s):
        base = cerebro.ruta_base
        if not _base_valida(base, cerebro.historico_csv):
            _construir_base(base, cerebro)
        respaldo = None
        if respaldar and cerebro.db.ruta.exists():
            carpeta = cerebro.db.ruta.parent / "respaldos"
            carpeta.mkdir(parents=True, exist_ok=True)
            respaldo = carpeta / f"{cerebro.db.ruta.stem}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.db"
            copiar_base(cerebro.db.ruta, respaldo)
        copiar_base(base, cerebro.db.ruta)
        cerebro.db.inicializar(cerebro.historico_csv, cerebro._reglas_actuales())   # versión de reglas vigente
        cerebro._cargar_secreto()
        with cerebro.db.lectura() as con:
            decisiones = con.execute("SELECT COUNT(*) FROM decision_log").fetchone()[0]
            pagos = leer_pagos(con)
        ref = cerebro.ref_date
        gastado = sum(p.monto_usd_cents for p in pagos
                      if (p.fecha_pago.year, p.fecha_pago.month) == (ref.year, ref.month))
        integra, _ = cerebro.verificar_cadena()
        return {
            "reiniciado_por": admin,
            "ts": datetime.now(UTC).isoformat(),
            "base": str(base),
            "respaldo": str(respaldo) if respaldo else None,
            "decisiones": decisiones,
            "pagos_historicos": sum(p.origen == "historico" for p in pagos),
            "pagos_simulados": sum(p.origen == "simulado" for p in pagos),
            "saldo_inicial_usd": str(cents_a_decimal(cerebro.reglas.saldo_inicial_mes_cents - gastado)),
            "cadena_integra": integra,
            "firma": cerebro.firmante.huella if cerebro.firmante else None,
        }
