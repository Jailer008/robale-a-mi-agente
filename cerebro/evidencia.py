"""Paquete de evidencia del veto (solo lectura): todo lo necesario para reconstruir una decisión.

Por factura_id reúne cada fila del registro (decisión inicial y resolución humana, sin
sobrescribir nada), la factura evaluada, el contenido exacto de las reglas usadas, el
documento original contra su SHA-256, las firmas, los eventos del comité y el pago simulado.
`responsable` identifica la regla, el agente o la persona que determinó el resultado.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cerebro.config import RAIZ
from cerebro.registro import verificar_cadena
from cerebro.tipos import tipo_de
from schemas import Decision

if TYPE_CHECKING:
    from cerebro import Cerebro

VERSION_CONTRATO = "1.0"
ADVERTENCIA = ("Pagos SIMULADOS: no hay conexión bancaria. PAGAR es una autorización simulada registrada en la "
               "tabla `pagos`, no una transferencia.")


def responsable(d: Decision) -> dict[str, Any]:
    if d.aprobador and d.aprobado is False:
        return {"tipo": "humano", "nombre": d.aprobador, "severidad": 2, "motivo": d.explicacion,
                "evidencia": "rechazo humano", "campo": None}
    if d.aprobador and d.decision == "PAGAR":
        return {"tipo": "humano", "nombre": d.aprobador, "severidad": 0, "motivo": d.explicacion,
                "evidencia": "aprobación humana", "campo": None}
    if not d.hallazgos:
        return {"tipo": "reglas", "nombre": "politica", "severidad": 0, "motivo": d.explicacion,
                "evidencia": f"cedar={d.cedar}", "campo": None}
    h = d.hallazgos[0]                     # ordenados de mayor a menor severidad
    if h.agente == "reglas":
        tipo, nombre = "regla", h.evidencia.removeprefix("regla=")
    else:
        tipo, nombre = ("agente" if tipo_de(h) == "riesgo" else tipo_de(h)), h.agente
    return {"tipo": tipo, "nombre": nombre, "severidad": h.severidad, "motivo": h.motivo,
            "evidencia": h.evidencia, "campo": h.campo}


def _documento_original(archivo: str, sha_esperado: str, datos: Path) -> dict[str, Any]:
    candidatos = [Path(archivo)] if Path(archivo).is_absolute() else [RAIZ / archivo, datos.parent / archivo]
    encontrado = next((c for c in candidatos if c.is_file()), None)
    coincide = None
    if encontrado is not None:
        coincide = hashlib.sha256(encontrado.read_bytes()).hexdigest() == sha_esperado
    return {"archivo": archivo, "sha256_esperado": sha_esperado, "encontrado": encontrado is not None,
            "coincide": coincide}


def paquete_evidencia(cerebro: Cerebro, factura_id: str) -> dict[str, Any]:
    firmante = cerebro.firmante
    with cerebro.db.lectura() as con:
        integra, fila_rota = verificar_cadena(con, firmante)
        filas = con.execute("SELECT id, decision_json, factura_json, firma, clave_firma FROM decision_log"
                            " WHERE factura_id = ? ORDER BY id", (factura_id,)).fetchall()
        if not filas:
            raise LookupError(f"No hay decisiones para {factura_id}")
        eventos = [dict(zip(("decision_id", "agente", "severidad", "probabilidad", "latencia_ms", "motivo", "tipo",
                             "ts"), fila, strict=True))
                   for fila in con.execute("SELECT decision_id, agente, severidad, probabilidad, latencia_ms, motivo,"
                                           " tipo, ts FROM eventos WHERE factura_id = ? ORDER BY id", (factura_id,))]
        reglas = dict(con.execute("SELECT version, contenido FROM reglas_versiones"))
        pago = con.execute("SELECT decision_id, monto, moneda, monto_usd_cents, fecha_pago FROM pagos"
                           " WHERE factura_id = ? AND origen = 'simulado'", (factura_id,)).fetchone()

    decisiones = []
    for fila_id, decision_json, _, firma, huella in filas:
        d = Decision.model_validate_json(decision_json)
        valida = (huella == firmante.huella and firmante.verificar(d.hash, firma)) if (firmante and firma) else None
        decisiones.append({"fila": fila_id, "decision": d.model_dump(mode="json"), "responsable": responsable(d),
                           "firma": {"presente": bool(firma), "clave": huella or None, "valida": valida}})
    final = Decision.model_validate_json(filas[-1][1])
    factura = json.loads(filas[0][2])
    usadas = {x["decision"]["version_reglas"] for x in decisiones}
    return {
        "version_contrato": VERSION_CONTRATO,
        "factura_id": factura_id,
        "advertencia": ADVERTENCIA,
        "cadena": {"integra": integra, "fila_rota": fila_rota, "firmada": firmante is not None,
                   "clave_publica": firmante.huella if firmante else None},
        "factura": factura,
        "documento_original": _documento_original(factura.get("archivo", ""), factura.get("id_documento", ""),
                                                  cerebro.datos),
        "reglas": {v: reglas.get(v) for v in sorted(usadas)},
        "decisiones": decisiones,
        "decision_final": final.model_dump(mode="json"),
        "autoridad_humana": {"aprobador": final.aprobador, "aprobado": final.aprobado} if final.aprobador else None,
        "responsable": responsable(final),
        "eventos": eventos,
        "pago_simulado": dict(zip(("decision_id", "monto", "moneda", "monto_usd_cents", "fecha_pago"), pago,
                                  strict=True)) if pago else None,
    }
