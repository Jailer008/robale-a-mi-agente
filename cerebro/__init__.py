"""Dev 2 · cerebro de decisión."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from cerebro.config import RAIZ, cargar_reglas, ref_date_configurada
from cerebro.contexto import Catalogo, Contexto, construir_contexto
from cerebro.db import BaseDatos
from schemas import FacturaCanonica


class Cerebro:
    def __init__(self, *, db_path: Path, datos: Path = RAIZ / "datos", reglas_path: Path = RAIZ / "reglas.yaml",
                 ref_date: date | None = None) -> None:
        self.datos = Path(datos)
        self.reglas = cargar_reglas(reglas_path)
        self.catalogo = Catalogo.cargar(self.datos)
        self.ref_date = ref_date or ref_date_configurada()
        self.db = BaseDatos(db_path)
        self.db.inicializar(self.datos / "historico_pagos.csv", self.reglas)

    def contexto(self, factura: FacturaCanonica) -> Contexto:
        with self.db.transaccion() as con:
            return construir_contexto(factura, con, self.catalogo, self.reglas, self.ref_date)
