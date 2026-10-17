from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from schemas import FacturaCanonica

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"


def cargar_yaml(nombre: str):
    return yaml.safe_load((DATOS / nombre).read_text(encoding="utf-8"))


def cargar_csv(nombre: str) -> list[dict[str, str]]:
    with (DATOS / nombre).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cargar_factura_json(numero: str) -> FacturaCanonica:
    ruta = DATOS / "facturas_json" / f"{numero}.json"
    return FacturaCanonica.model_validate_json(ruta.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def reglas() -> dict:
    return yaml.safe_load((RAIZ / "reglas.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def proveedores() -> list[dict]:
    return cargar_yaml("proveedores.yaml")


@pytest.fixture(scope="session")
def contratos() -> list[dict]:
    return cargar_yaml("contratos.yaml")


@pytest.fixture(scope="session")
def tasas() -> dict:
    return cargar_yaml("tasas_fx.yaml")


@pytest.fixture(scope="session")
def historico() -> list[dict[str, str]]:
    return cargar_csv("historico_pagos.csv")


@pytest.fixture(scope="session")
def ground_truth() -> list[dict[str, str]]:
    return cargar_csv("ground_truth.csv")


@pytest.fixture(scope="session")
def facturas() -> dict[str, FacturaCanonica]:
    return {f"{n:02d}": cargar_factura_json(f"{n:02d}") for n in range(1, 16)}
