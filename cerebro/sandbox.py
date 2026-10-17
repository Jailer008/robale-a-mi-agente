"""Policy Sandbox: "¿qué habría decidido el cerebro con otros límites?" — SOLO LECTURA.

Evalúa la misma factura con las reglas actuales y con reglas hipotéticas, sobre una instantánea
de la base abierta con `PRAGMA query_only`: no se ejecuta ningún pago y no se modifican
reglas.yaml, pagos, decision_log ni eventos. Solo corren los detectores deterministas (la capa
semántica no se consulta). Un veto de agente (texto oculto, duplicado exacto) no se desarma
cambiando límites: el sandbox lo muestra.
"""

from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from cerebro.agentes import AGENTES
from cerebro.agregador import agregar, explicar
from cerebro.config import Reglas, cargar_reglas
from cerebro.contexto import construir_contexto
from cerebro.dinero import a_centavos, a_decimal
from cerebro.reglas import evaluar
from cerebro.tipos import causa, fallo
from schemas import Decision, FacturaCanonica, Hallazgo

if TYPE_CHECKING:
    from cerebro import Cerebro

ADVERTENCIA = ("Simulación de solo lectura: no se ejecutó ningún pago y no se modificaron reglas.yaml, pagos, "
               "decision_log ni eventos.")
# clave en reglas.yaml → (campo de Reglas, tipo)
CAMBIABLES: dict[str, tuple[str, str]] = {
    "limite_pago_usd": ("limite_pago_cents", "usd"),
    "tope_duro_usd": ("tope_duro_cents", "usd"),
    "limite_mensual_proveedor_usd": ("limite_mes_proveedor_cents", "usd"),
    "limite_mensual_global_usd": ("limite_mes_global_cents", "usd"),
    "saldo_disponible_usd": ("saldo_inicial_mes_cents", "usd"),
    "tolerancia_contrato": ("tolerancia_contrato", "fraccion"),
    "tolerancia_fx": ("tolerancia_fx", "fraccion"),
    "tolerancia_monto_duplicado": ("tolerancia_monto_duplicado", "fraccion"),
    "umbral_sospecha": ("umbral_sospecha", "fraccion"),
    "ventana_duplicados_dias": ("ventana_duplicados_dias", "dias"),
}


def _texto(valor: Decimal) -> str:
    return format(valor.quantize(Decimal(1)) if valor == valor.to_integral_value() else valor.normalize(), "f")


def _actual(reglas: Reglas, campo: str, tipo: str) -> str:
    valor = getattr(reglas, campo)
    return _texto(Decimal(valor) / 100) if tipo == "usd" else str(valor)


def aplicar_cambios(reglas: Reglas, cambios: Mapping[str, Any]) -> tuple[Reglas, dict[str, dict[str, str]]]:
    if not cambios:
        raise ValueError("Indique al menos un límite a simular")
    nuevos: dict[str, Any] = {}
    resumen: dict[str, dict[str, str]] = {}
    for clave, valor in cambios.items():
        if clave not in CAMBIABLES:
            raise ValueError(f"'{clave}' no se puede simular; opciones: {', '.join(sorted(CAMBIABLES))}")
        if isinstance(valor, bool):
            raise ValueError(f"{clave}: valor inválido {valor!r}")
        campo, tipo = CAMBIABLES[clave]
        numero = a_decimal(valor)                         # rechaza NaN, infinito y texto
        if numero < 0 or (tipo == "fraccion" and numero > 1) or (tipo == "dias" and numero != int(numero)):
            raise ValueError(f"{clave}: valor fuera de rango {valor!r}")
        nuevos[campo] = a_centavos(numero) if tipo == "usd" else int(numero) if tipo == "dias" else numero
        resumen[clave] = {"antes": _actual(reglas, campo, tipo), "despues": _texto(numero)}
    firma = hashlib.sha256(repr(sorted(nuevos.items())).encode()).hexdigest()[:12]
    return dataclasses.replace(reglas, version=f"sandbox:{reglas.version[:12]}:{firma}", **nuevos), resumen


def _evaluar(cerebro: Cerebro, con: sqlite3.Connection, factura: FacturaCanonica, reglas: Reglas) -> dict[str, Any]:
    ctx = construir_contexto(factura, con, cerebro.catalogo, reglas, cerebro.ref_date)
    evaluacion = evaluar(ctx)
    hallazgos: list[Hallazgo] = []
    for nombre, agente in AGENTES:                       # deterministas y síncronos: sin red ni modelos
        try:
            hallazgos += agente(factura, ctx)
        except Exception as error:
            hallazgos.append(fallo(nombre, f"No se pudo verificar con el agente {nombre} ({causa(error)}).",
                                   causa(error)))
    resultado = agregar(extraccion_ok=ctx.extraccion_ok, cedar=evaluacion.cedar, fallas=evaluacion.fallas,
                        hallazgos=hallazgos)
    return {"decision": resultado.decision, "explicacion": explicar(resultado, ctx), "cedar": evaluacion.cedar,
            "reglas_fallidas": [f.regla for f in evaluacion.fallas],
            "hallazgos": [h.motivo for h in resultado.hallazgos]}


def _razon(original: dict[str, Any], simulada: dict[str, Any], cambios: dict[str, dict[str, str]],
           reglas_cambiadas: list[dict[str, str]]) -> str:
    texto_cambios = ", ".join(f"{k} {v['antes']} → {v['despues']}" for k, v in cambios.items())
    efectos = "; ".join(f"la regla '{r['regla']}' {'deja de fallar' if r['despues'] == 'cumple' else 'pasa a fallar'}"
                        for r in reglas_cambiadas)
    if original["decision"] != simulada["decision"]:
        return (f"Con {texto_cambios}, la decisión pasa de {original['decision']} a {simulada['decision']}: "
                f"{efectos or 'cambian los hallazgos'}.")
    manda = simulada["hallazgos"][0] if simulada["hallazgos"] else "todas las reglas se cumplen"
    extra = f" ({efectos})" if efectos else ""
    return f"Con {texto_cambios}, la decisión sigue siendo {simulada['decision']}{extra}: manda «{manda}»."


def simular(cerebro: Cerebro, factura: FacturaCanonica | str, cambios: Mapping[str, Any]) -> dict[str, Any]:
    base = cargar_reglas(cerebro.reglas_path)
    hipoteticas, resumen = aplicar_cambios(base, cambios)
    registrada: Decision | None = None
    con = sqlite3.connect(cerebro.db.ruta, timeout=30)
    try:
        con.execute("PRAGMA query_only = ON")             # cualquier escritura por esta conexión falla
        con.execute("BEGIN")
        if isinstance(factura, str):
            fila = con.execute("SELECT decision_json, factura_json FROM decision_log WHERE factura_id = ?"
                               " ORDER BY id DESC LIMIT 1", (factura,)).fetchone()
            if fila is None:
                raise LookupError(f"No hay decisiones para {factura}")
            registrada = Decision.model_validate_json(fila[0])
            factura = FacturaCanonica.model_validate_json(fila[1])
        original = _evaluar(cerebro, con, factura, base)
        simulada = _evaluar(cerebro, con, factura, hipoteticas)
        con.execute("ROLLBACK")
    finally:
        con.close()

    antes, despues = set(original["reglas_fallidas"]), set(simulada["reglas_fallidas"])
    reglas_cambiadas = [{"regla": r, "antes": "falla" if r in antes else "cumple",
                         "despues": "falla" if r in despues else "cumple"} for r in sorted(antes ^ despues)]
    return {
        "modo": "SANDBOX",
        "advertencia": ADVERTENCIA,
        "factura_id": factura.id_documento,
        "numero_factura": factura.numero_factura,
        "proveedor": factura.proveedor,
        "cambios": resumen,
        "original": original,
        "simulada": simulada,
        "cambia_resultado": original["decision"] != simulada["decision"],
        "reglas_que_cambiaron": reglas_cambiadas,
        "razon": _razon(original, simulada, resumen, reglas_cambiadas),
        "capa_semantica": "no se consulta en el sandbox (solo detectores deterministas)",
        "decision_registrada": registrada.model_dump(mode="json") if registrada else None,
    }
