"""SQLite del cerebro: pagos, decision_log, reglas_versiones y eventos.

Cada operación financiera corre en una transacción `BEGIN IMMEDIATE`: un solo
escritor a la vez, así dos solicitudes simultáneas no pueden gastar el mismo saldo
ni pagar dos veces la misma factura. Los pagos son autorizaciones SIMULADAS.
"""

from __future__ import annotations

import csv
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from cerebro.config import Reglas
from cerebro.dinero import a_centavos, a_decimal
from cerebro.normalizar import clave, clave_numero

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pagos (
    id               INTEGER PRIMARY KEY,
    factura_id       TEXT NOT NULL UNIQUE,
    proveedor        TEXT NOT NULL,
    proveedor_clave  TEXT NOT NULL,
    numero_factura   TEXT NOT NULL,
    numero_clave     TEXT NOT NULL,
    monto            TEXT NOT NULL,              -- Decimal como texto, en la moneda original
    moneda           TEXT NOT NULL,
    monto_usd_cents  INTEGER NOT NULL,
    fecha_pago       TEXT NOT NULL,              -- AAAA-MM-DD
    origen           TEXT NOT NULL CHECK (origen IN ('historico', 'simulado')),
    decision_id      INTEGER,
    UNIQUE (proveedor_clave, numero_clave)       -- nunca dos pagos de la misma factura
);
CREATE TABLE IF NOT EXISTS decision_log (
    id             INTEGER PRIMARY KEY,
    factura_id     TEXT NOT NULL,
    ts             TEXT NOT NULL,
    decision       TEXT NOT NULL,
    estado         TEXT NOT NULL,
    decision_json  TEXT NOT NULL,
    factura_json   TEXT NOT NULL,
    hash_prev      TEXT NOT NULL,
    hash           TEXT NOT NULL UNIQUE,
    firma          TEXT NOT NULL DEFAULT '',     -- Ed25519 sobre `hash` (hex); '' si no hay clave
    clave_firma    TEXT NOT NULL DEFAULT '',     -- huella de la clave pública que firmó
    clave_idempotencia TEXT                      -- reintentos de reanudar(); no autoriza nada
);
CREATE INDEX IF NOT EXISTS ix_decision_factura ON decision_log (factura_id, id);
CREATE TABLE IF NOT EXISTS reglas_versiones (
    version    TEXT PRIMARY KEY,
    contenido  TEXT NOT NULL,
    cargada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id            INTEGER PRIMARY KEY,
    factura_id    TEXT NOT NULL,
    decision_id   INTEGER,
    agente        TEXT NOT NULL,
    severidad     INTEGER NOT NULL CHECK (severidad IN (0, 1, 2)),
    probabilidad  REAL,
    latencia_ms   INTEGER NOT NULL,
    motivo        TEXT NOT NULL,
    ts            TEXT NOT NULL,
    tipo          TEXT NOT NULL DEFAULT 'sin_hallazgos'  -- riesgo | fallo_tecnico | sin_evidencia | sin_hallazgos
);
CREATE INDEX IF NOT EXISTS ix_eventos_factura ON eventos (factura_id, id);
CREATE TABLE IF NOT EXISTS metadatos (
    clave  TEXT PRIMARY KEY,
    valor  TEXT NOT NULL
);
"""

# Columnas agregadas en G3: una base creada en G2 se migra al iniciar (ALTER TABLE idempotente).
_MIGRACIONES = {
    "decision_log": {"firma": "TEXT NOT NULL DEFAULT ''", "clave_firma": "TEXT NOT NULL DEFAULT ''",
                     "clave_idempotencia": "TEXT"},
    "eventos": {"tipo": "TEXT NOT NULL DEFAULT 'sin_hallazgos'"},
}


@dataclass(frozen=True, slots=True)
class Pago:
    factura_id: str
    proveedor: str
    numero_factura: str
    monto: str
    moneda: str
    monto_usd_cents: int
    fecha_pago: date
    origen: str


def ahora() -> str:
    return datetime.now(UTC).isoformat()


class BaseDatos:
    def __init__(self, ruta: Path) -> None:
        self.ruta = Path(ruta)

    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.ruta, timeout=30, isolation_level=None, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @contextmanager
    def lectura(self) -> Iterator[sqlite3.Connection]:
        """Instantánea consistente de solo lectura (no toma el candado de escritura)."""
        con = self._conectar()
        try:
            con.execute("BEGIN")
            try:
                yield con
            finally:
                con.execute("ROLLBACK")
        finally:
            con.close()

    @contextmanager
    def transaccion(self) -> Iterator[sqlite3.Connection]:
        """Transacción de escritura exclusiva: o se aplica todo, o nada."""
        con = self._conectar()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        finally:
            con.close()

    def inicializar(self, historico_csv: Path, reglas: Reglas) -> None:
        """Crea el esquema y carga el histórico. Idempotente: repetirlo no duplica filas."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        con = self._conectar()
        try:
            con.executescript(ESQUEMA)
            for tabla, columnas in _MIGRACIONES.items():
                existentes = {fila[1] for fila in con.execute(f"PRAGMA table_info({tabla})")}  # noqa: S608
                for nombre, tipo in columnas.items():
                    if nombre not in existentes:
                        con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
            con.execute("CREATE INDEX IF NOT EXISTS ix_decision_idem ON decision_log (clave_idempotencia)")
        finally:
            con.close()
        with self.transaccion() as con:
            # Secreto aleatorio de esta base para el HMAC de cuentas (cerebro.privacidad). No sale de la base.
            con.execute("INSERT OR IGNORE INTO metadatos (clave, valor) VALUES ('secreto_cuentas', ?)",
                        (secrets.token_hex(32),))
            con.execute(
                "INSERT OR IGNORE INTO reglas_versiones (version, contenido, cargada_en) VALUES (?, ?, ?)",
                (reglas.version, reglas.contenido, ahora()),
            )
            with Path(historico_csv).open(encoding="utf-8", newline="") as archivo:
                for fila in csv.DictReader(archivo):
                    con.execute(
                        "INSERT OR IGNORE INTO pagos (factura_id, proveedor, proveedor_clave, numero_factura,"
                        " numero_clave, monto, moneda, monto_usd_cents, fecha_pago, origen)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'historico')",
                        (
                            fila["factura_id"], fila["proveedor"], clave(fila["proveedor"]),
                            fila["numero_factura"], clave_numero(fila["numero_factura"]),
                            str(a_decimal(fila["monto"])), fila["moneda"].strip().upper(),
                            a_centavos(a_decimal(fila["monto_usd"])),
                            date.fromisoformat(fila["fecha_pago"]).isoformat(),
                        ),
                    )
            # Bases creadas antes de clave_numero: se recalcula la clave de número (idempotente).
            for fila_id, numero in con.execute("SELECT id, numero_factura FROM pagos").fetchall():
                con.execute("UPDATE pagos SET numero_clave = ? WHERE id = ?", (clave_numero(numero), fila_id))


def leer_secreto(con: sqlite3.Connection) -> bytes:
    fila = con.execute("SELECT valor FROM metadatos WHERE clave = 'secreto_cuentas'").fetchone()
    if fila is None:
        raise RuntimeError("La base no tiene secreto de cuentas: inicialícela con BaseDatos.inicializar")
    return bytes.fromhex(fila[0])


def leer_pagos(con: sqlite3.Connection) -> list[Pago]:
    filas = con.execute(
        "SELECT factura_id, proveedor, numero_factura, monto, moneda, monto_usd_cents, fecha_pago, origen"
        " FROM pagos ORDER BY id"
    ).fetchall()
    return [Pago(f[0], f[1], f[2], f[3], f[4], int(f[5]), date.fromisoformat(f[6]), f[7]) for f in filas]


def insertar_pago_simulado(con: sqlite3.Connection, *, factura_id: str, proveedor: str, numero_factura: str,
                           monto: str, moneda: str, monto_usd_cents: int, fecha_pago: date,
                           decision_id: int) -> None:
    con.execute(
        "INSERT INTO pagos (factura_id, proveedor, proveedor_clave, numero_factura, numero_clave, monto, moneda,"
        " monto_usd_cents, fecha_pago, origen, decision_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'simulado', ?)",
        (factura_id, proveedor, clave(proveedor), numero_factura, clave_numero(numero_factura), monto, moneda,
         monto_usd_cents, fecha_pago.isoformat(), decision_id),
    )


def _historico_esperado(historico_csv: Path) -> set[tuple]:
    with Path(historico_csv).open(encoding="utf-8", newline="") as archivo:
        return {(f["factura_id"], f["proveedor"], f["numero_factura"], str(a_decimal(f["monto"])),
                 f["moneda"].strip().upper(), a_centavos(a_decimal(f["monto_usd"])),
                 date.fromisoformat(f["fecha_pago"]).isoformat()) for f in csv.DictReader(archivo)}


def verificar_pagos(con: sqlite3.Connection, historico_csv: Path) -> list[str]:
    """El saldo sale de `pagos`: si alguien lo manipula, nadie puede cobrar.

    - Las filas históricas deben ser exactamente las del CSV de origen.
    - Cada pago simulado debe corresponder 1:1 a una decisión PAGAR del registro, por el mismo monto.
    Devuelve los problemas encontrados (lista vacía = íntegro).
    """
    problemas: list[str] = []
    historicas = {tuple(f) for f in con.execute(
        "SELECT factura_id, proveedor, numero_factura, monto, moneda, monto_usd_cents, fecha_pago"
        " FROM pagos WHERE origen = 'historico'")}
    if historicas != _historico_esperado(historico_csv):
        problemas.append("el histórico de pagos no coincide con historico_pagos.csv")

    pagar = {}
    for fila_id, factura_id, decision_json in con.execute(
            "SELECT id, factura_id, decision_json FROM decision_log WHERE decision = 'PAGAR'"):
        try:
            monto = json.loads(decision_json)["monto_usd"]
            pagar[fila_id] = (factura_id, a_centavos(a_decimal(monto)))
        except (KeyError, TypeError, ValueError):
            problemas.append(f"la decisión {fila_id} no tiene un monto legible")
    simulados = {}
    for decision_id, factura_id, cents in con.execute(
            "SELECT decision_id, factura_id, monto_usd_cents FROM pagos WHERE origen = 'simulado'"):
        if decision_id in simulados or decision_id not in pagar:
            problemas.append(f"pago simulado de {factura_id[:12]} sin decisión PAGAR que lo respalde")
            continue
        simulados[decision_id] = (factura_id, int(cents))
    for decision_id, esperado in pagar.items():
        if simulados.get(decision_id) != esperado:
            problemas.append(f"la decisión PAGAR {decision_id} no coincide con su pago simulado")
    return problemas
