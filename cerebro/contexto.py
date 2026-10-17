"""Constructor de contexto (100 % código): todo lo que las reglas y los agentes necesitan.

Montos en centavos enteros de USD. Si falta un dato crítico se anota en `problemas`
y la decisión nunca puede ser PAGAR.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from cerebro.config import Reglas
from cerebro.db import Pago, leer_pagos
from cerebro.dinero import a_centavos, a_decimal, numero_es
from cerebro.normalizar import clave
from schemas import FacturaCanonica

_TOLERANCIA_ARITMETICA = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class TasaFx:
    moneda: str
    unidades_por_usd: Decimal
    fuente: str
    fecha: str


@dataclass(frozen=True, slots=True)
class Catalogo:
    proveedores: tuple[dict[str, Any], ...]
    contratos: tuple[dict[str, Any], ...]
    tasas: dict[str, TasaFx]

    @classmethod
    def cargar(cls, datos: Path) -> Catalogo:
        leer = lambda nombre: yaml.safe_load((Path(datos) / nombre).read_text(encoding="utf-8"))  # noqa: E731
        tasas = {}
        for moneda, t in (leer("tasas_fx.yaml") or {}).items():
            unidades = a_decimal(t["unidades_por_usd"])
            if unidades <= 0:
                continue                      # una tasa inválida equivale a no tener tasa
            tasas[str(moneda).upper()] = TasaFx(str(moneda).upper(), unidades, str(t.get("fuente", "")),
                                               str(t.get("fecha", "")))
        return cls(tuple(leer("proveedores.yaml") or ()), tuple(leer("contratos.yaml") or ()), tasas)

    def proveedor(self, nombre: str) -> dict[str, Any] | None:
        buscado = clave(nombre)
        if not buscado:
            return None
        return next((p for p in self.proveedores if clave(p["nombre"]) == buscado), None)

    def contrato_de(self, nombre_proveedor: str) -> dict[str, Any] | None:
        return next((c for c in self.contratos if clave(c["proveedor"]) == clave(nombre_proveedor)), None)


@dataclass(frozen=True, slots=True)
class Contexto:
    ref_date: date
    reglas: Reglas
    moneda: str
    monto_original: Decimal | None
    fx: TasaFx | None
    monto_usd_cents: int | None
    gastado_mes_proveedor_cents: int
    gastado_mes_global_cents: int
    saldo_cents: int
    proveedor: dict[str, Any] | None
    beneficiario_permitido: bool
    beneficiario_bloqueado: bool
    cuenta_coincide: bool
    contrato: dict[str, Any] | None
    extraccion_ok: bool
    pagos: tuple[Pago, ...] = ()
    problemas: list[str] = field(default_factory=list)
    nombre_factura: str = ""
    cuenta_factura: str | None = None
    diferencias: tuple[str, ...] = ()


def _mismo_mes(a: date, b: date) -> bool:
    return (a.year, a.month) == (b.year, b.month)


def _aritmetica(factura: FacturaCanonica, problemas: list[str]) -> Decimal | None:
    """Revalida la factura en Decimal (defensa en profundidad: puede no venir de extraer())."""
    try:
        total = a_decimal(factura.total)
        subtotal = a_decimal(factura.subtotal)
        impuestos = a_decimal(factura.impuestos)
    except ValueError:
        problemas.append("El total, el subtotal o los impuestos no son un número válido")
        return None
    if total <= 0:
        problemas.append("El total debe ser mayor que cero")
    if not factura.lineas:
        problemas.append("La factura no tiene líneas que verificar")
    suma = Decimal(0)
    for i, linea in enumerate(factura.lineas, start=1):
        try:
            cantidad, precio, total_linea = (a_decimal(linea.cantidad), a_decimal(linea.precio_unitario),
                                             a_decimal(linea.total))
        except ValueError:
            problemas.append(f"Línea {i}: cantidad, precio o total no son números válidos")
            continue
        if abs(cantidad * precio - total_linea) > _TOLERANCIA_ARITMETICA:
            problemas.append(f"Línea {i}: {numero_es(cantidad)} × {numero_es(precio)} no da {numero_es(total_linea)}")
        suma += total_linea
    if factura.lineas and abs(suma - subtotal) > _TOLERANCIA_ARITMETICA:
        problemas.append(f"Las líneas suman {numero_es(suma)} pero el subtotal dice {numero_es(subtotal)}")
    if abs(subtotal + impuestos - total) > _TOLERANCIA_ARITMETICA:
        problemas.append(f"Subtotal + impuestos = {numero_es(subtotal + impuestos)}, pero el total dice "
                         f"{numero_es(total)}")
    return total if total > 0 else None


def construir_contexto(factura: FacturaCanonica, con: sqlite3.Connection, catalogo: Catalogo, reglas: Reglas,
                       ref_date: date) -> Contexto:
    problemas: list[str] = []
    if not factura.proveedor.strip():
        problemas.append("Falta el proveedor")
    if not factura.numero_factura.strip():
        problemas.append("Falta el número de factura")

    monto = _aritmetica(factura, problemas)
    moneda = factura.moneda.strip().upper()
    fx = catalogo.tasas.get(moneda)
    if fx is None:
        problemas.append(f"No hay tasa FX confiable para '{moneda or '(vacía)'}'")
    monto_usd_cents = a_centavos(monto / fx.unidades_por_usd) if (monto is not None and fx) else None

    pagos = tuple(leer_pagos(con))
    del_mes = [p for p in pagos if _mismo_mes(p.fecha_pago, ref_date)]
    gastado_global = sum(p.monto_usd_cents for p in del_mes)
    gastado_proveedor = sum(p.monto_usd_cents for p in del_mes if clave(p.proveedor) == clave(factura.proveedor))

    proveedor = catalogo.proveedor(factura.proveedor)
    bloqueado = bool(proveedor and proveedor.get("bloqueado"))
    permitido = bool(proveedor and proveedor.get("permitido") is True and not bloqueado)
    cuenta_ok = bool(proveedor and factura.cuenta_bancaria
                     and clave(factura.cuenta_bancaria) == clave(proveedor.get("cuenta_registrada")))
    contrato = catalogo.contrato_de(proveedor["nombre"]) if permitido else None

    return Contexto(
        ref_date=ref_date,
        reglas=reglas,
        moneda=moneda,
        monto_original=monto,
        fx=fx,
        monto_usd_cents=monto_usd_cents,
        gastado_mes_proveedor_cents=gastado_proveedor,
        gastado_mes_global_cents=gastado_global,
        saldo_cents=reglas.saldo_inicial_mes_cents - gastado_global,
        proveedor=proveedor,
        beneficiario_permitido=permitido,
        beneficiario_bloqueado=bloqueado,
        cuenta_coincide=cuenta_ok,
        contrato=contrato,
        extraccion_ok=bool(factura.extraccion_ok),
        pagos=pagos,
        problemas=problemas,
        nombre_factura=factura.proveedor.strip(),
        cuenta_factura=factura.cuenta_bancaria,
        diferencias=tuple(factura.diferencias),
    )
