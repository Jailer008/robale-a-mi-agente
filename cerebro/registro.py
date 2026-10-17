"""Registro auditable: cada Decision se encadena con la anterior por SHA-256 y se firma con Ed25519.

hash  = sha256(hash_prev + json_canonico(decision_sin_hash) + sha256(factura_json))
firma = Ed25519(hash)   (si hay clave configurada)

Además de la fórmula de DEV2 §4 se sella la factura evaluada: `reanudar` la reevalúa desde
el registro, así que alterarla también debe romper la cadena. Las filas nunca se actualizan:
una resolución humana es una fila nueva que apunta a la misma factura_id.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from cerebro.firma import Firmante
from schemas import Decision

GENESIS = "0" * 64


def json_canonico(datos: Any) -> str:
    return json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def calcular_hash(hash_prev: str, decision_sin_hash: dict[str, Any], factura_json: str) -> str:
    return _sha(hash_prev + json_canonico(decision_sin_hash) + _sha(factura_json))


def sellar(con: sqlite3.Connection, decision: Decision, factura_json: str, firmante: Firmante | None = None,
           clave_idempotencia: str | None = None) -> tuple[Decision, int]:
    """Encadena, firma y guarda la decisión dentro de la transacción abierta. Devuelve (decisión, id de fila)."""
    previa = con.execute("SELECT hash FROM decision_log ORDER BY id DESC LIMIT 1").fetchone()
    hash_prev = previa[0] if previa else GENESIS
    datos = decision.model_copy(update={"hash_prev": hash_prev, "hash": ""}).model_dump(mode="json")
    datos.pop("hash")
    sello = calcular_hash(hash_prev, datos, factura_json)
    final = decision.model_copy(update={"hash_prev": hash_prev, "hash": sello})
    cursor = con.execute(
        "INSERT INTO decision_log (factura_id, ts, decision, estado, decision_json, factura_json, hash_prev, hash,"
        " firma, clave_firma, clave_idempotencia) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (final.factura_id, final.ts.isoformat(), final.decision, final.estado,
         json_canonico(final.model_dump(mode="json")), factura_json, hash_prev, sello,
         firmante.firmar(sello) if firmante else "", firmante.huella if firmante else "", clave_idempotencia),
    )
    return final, int(cursor.lastrowid)


def verificar_cadena(con: sqlite3.Connection, firmante: Firmante | None = None) -> tuple[bool, int | None]:
    """Recalcula toda la cadena (y las firmas si hay clave). (True, None) si está íntegra;
    si no, (False, id de la primera fila alterada)."""
    esperado_prev = GENESIS
    filas = con.execute("SELECT id, factura_id, decision, estado, decision_json, factura_json, hash_prev, hash,"
                        " firma, clave_firma FROM decision_log ORDER BY id").fetchall()
    for fila_id, factura_id, decision, estado, decision_json, factura_json, hash_prev, sello, firma, huella in filas:
        try:
            datos = json.loads(decision_json)
        except (TypeError, ValueError):
            return False, fila_id
        if (hash_prev != esperado_prev or datos.get("hash_prev") != hash_prev or datos.get("hash") != sello
                or datos.get("decision") != decision or datos.get("estado") != estado
                or datos.get("factura_id") != factura_id):
            return False, fila_id
        datos.pop("hash")
        try:
            if calcular_hash(hash_prev, datos, factura_json) != sello:
                return False, fila_id
        except (TypeError, ValueError):
            return False, fila_id
        if firmante is not None and (huella != firmante.huella or not firmante.verificar(sello, firma)):
            return False, fila_id
        esperado_prev = sello
    return True, None
