"""Reglas de reglas.yaml en centavos y fecha de referencia independiente del reloj."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from cerebro.dinero import a_centavos, a_decimal

RAIZ = Path(__file__).resolve().parent.parent
REF_DATE_POR_DEFECTO = date(2026, 10, 17)     # referencia de los fixtures del hackathon


@dataclass(frozen=True, slots=True)
class Reglas:
    version: str                               # SHA-256 del contenido de reglas.yaml
    contenido: str
    empresa: str
    limite_pago_cents: int
    tope_duro_cents: int
    limite_mes_proveedor_cents: int
    limite_mes_global_cents: int
    saldo_inicial_mes_cents: int
    tolerancia_contrato: Decimal
    tolerancia_fx: Decimal
    umbral_sospecha: Decimal
    ventana_duplicados_dias: int
    tolerancia_monto_duplicado: Decimal


def cargar_reglas(ruta: Path) -> Reglas:
    crudo = Path(ruta).read_bytes()
    datos = yaml.safe_load(crudo.decode("utf-8"))
    usd = lambda clave: a_centavos(a_decimal(datos[clave]))  # noqa: E731
    return Reglas(
        version=hashlib.sha256(crudo).hexdigest(),
        contenido=crudo.decode("utf-8"),
        empresa=str(datos["empresa"]),
        limite_pago_cents=usd("limite_pago_usd"),
        tope_duro_cents=usd("tope_duro_usd"),
        limite_mes_proveedor_cents=usd("limite_mensual_proveedor_usd"),
        limite_mes_global_cents=usd("limite_mensual_global_usd"),
        saldo_inicial_mes_cents=usd("saldo_disponible_usd"),
        tolerancia_contrato=a_decimal(datos["tolerancia_contrato"]),
        tolerancia_fx=a_decimal(datos["tolerancia_fx"]),
        umbral_sospecha=a_decimal(datos["umbral_sospecha"]),
        ventana_duplicados_dias=int(datos["ventana_duplicados_dias"]),
        tolerancia_monto_duplicado=a_decimal(datos["tolerancia_monto_duplicado"]),
    )


def ref_date_configurada() -> date:
    """REF_DATE (AAAA-MM-DD) o 2026-10-17. Una fecha inválida es un error, no un valor por defecto."""
    valor = os.environ.get("REF_DATE")
    if not valor:
        return REF_DATE_POR_DEFECTO
    return date.fromisoformat(valor.strip())
