"""Oráculo de reglas de dinero y duplicados (misma semántica que documenta datos/README.md).

Lo comparten los tests del set de 15 facturas y los de las facturas base del modo en vivo.
Trabaja con cualquier objeto que tenga proveedor, moneda, total y fecha_emision.
"""

from __future__ import annotations

from datetime import date, timedelta

HOY = date(2026, 10, 17)          # fecha de referencia fija: los tests no dependen del reloj
FRENAN = {"tope_duro", "mensual_proveedor", "mensual_global", "saldo"}


def a_usd(monto: float, moneda: str, tasas: dict) -> float:
    return round(monto / (tasas | {"USD": {"unidades_por_usd": 1}})[moneda]["unidades_por_usd"], 2)


def proveedor_por_nombre(proveedores: list[dict], nombre: str) -> dict | None:
    return next((p for p in proveedores if p["nombre"] == nombre), None)


def contrato_de(contratos: list[dict], proveedor: str) -> dict | None:
    return next((c for c in contratos if c["proveedor"] == proveedor), None)


def pagos_del_mes(historico: list[dict]) -> list[dict]:
    return [
        p for p in historico
        if date.fromisoformat(p["fecha_pago"]).replace(day=1) == HOY.replace(day=1)
    ]


def candidatos_duplicado(f, historico: list[dict], reglas: dict) -> list[dict]:
    ventana = timedelta(days=reglas["ventana_duplicados_dias"])
    tol = reglas["tolerancia_monto_duplicado"]
    salida = []
    for p in historico:
        if p["proveedor"] != f.proveedor or p["moneda"] != f.moneda:
            continue
        monto = float(p["monto"])
        if abs(monto - f.total) / monto > tol:
            continue
        if abs(date.fromisoformat(p["fecha_pago"]) - f.fecha_emision) > ventana:
            continue
        salida.append(p)
    return salida


def reglas_de_dinero(f, gastado_prov, gastado_global, saldo, reglas, tasas) -> set[str]:
    usd = a_usd(f.total, f.moneda, tasas)
    disparadas = set()
    if usd > reglas["tope_duro_usd"]:
        disparadas.add("tope_duro")
    elif usd > reglas["limite_pago_usd"]:
        disparadas.add("limite_pago")
    if gastado_prov.get(f.proveedor, 0) + usd > reglas["limite_mensual_proveedor_usd"]:
        disparadas.add("mensual_proveedor")
    if gastado_global + usd > reglas["limite_mensual_global_usd"]:
        disparadas.add("mensual_global")
    if usd > saldo:
        disparadas.add("saldo")
    return disparadas


def estado_inicial(historico: list[dict], reglas: dict):
    gastado_prov: dict[str, float] = {}
    for p in pagos_del_mes(historico):
        gastado_prov[p["proveedor"]] = gastado_prov.get(p["proveedor"], 0) + float(p["monto_usd"])
    gastado_global = sum(gastado_prov.values())
    saldo = reglas["saldo_disponible_usd"] - gastado_global
    return gastado_prov, gastado_global, saldo
