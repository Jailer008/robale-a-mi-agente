"""Mide qué tan bien lee el extractor contra los JSON a mano.

    uv run python -m extraccion.medir [--salida resultados_extraccion.json]

Usa las APIs reales (necesita GEMINI_API_KEY y ANTHROPIC_API_KEY en .env).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from extraccion.comparador import normalizar_texto
from schemas import FacturaCanonica

CAMPOS = [
    "proveedor", "id_fiscal", "cuenta_bancaria", "numero_factura", "fecha_emision",
    "fecha_vencimiento", "moneda", "subtotal", "impuestos", "total", "referencia_contrato", "lineas",
]
TEXTO = {"proveedor", "id_fiscal", "cuenta_bancaria", "numero_factura", "moneda", "referencia_contrato"}
NUMERO = {"subtotal", "impuestos", "total"}
TOL = 0.01


def _igual(campo: str, esperado: FacturaCanonica, obtenido: FacturaCanonica) -> bool:
    a, b = getattr(esperado, campo), getattr(obtenido, campo)
    if campo in TEXTO:
        return normalizar_texto(a) == normalizar_texto(b)
    if campo in NUMERO:
        return abs(a - b) <= TOL
    if campo == "lineas":
        return len(a) == len(b) and all(
            abs(x.cantidad - y.cantidad) <= TOL and abs(x.precio_unitario - y.precio_unitario) <= TOL
            and abs(x.total - y.total) <= TOL
            for x, y in zip(a, b, strict=True)
        )
    return a == b


@dataclass
class Reporte:
    n: int
    acierto: dict[str, float]
    fallos: dict[str, list[str]]
    extraccion_ok_correcta: float
    texto_oculto_correcto: float
    detalle: list[dict] = field(default_factory=list)

    def como_texto(self) -> str:
        filas = [f"Facturas medidas: {self.n}", "", f"{'campo':<22}{'acierto':>9}"]
        filas += [f"{c:<22}{self.acierto[c] * 100:>8.0f}%" for c in CAMPOS]
        filas += [
            "",
            f"{'extraccion_ok correcto':<22}{self.extraccion_ok_correcta * 100:>8.0f}%",
            f"{'texto oculto correcto':<22}{self.texto_oculto_correcto * 100:>8.0f}%",
        ]
        for campo, archivos in self.fallos.items():
            if archivos:
                filas.append(f"  falla {campo}: {', '.join(archivos)}")
        return "\n".join(filas)


def medir(pares: list[tuple[FacturaCanonica, FacturaCanonica]]) -> Reporte:
    n = len(pares)
    fallos = {c: [e.archivo for e, o in pares if not _igual(c, e, o)] for c in CAMPOS}
    ok = sum(e.extraccion_ok == o.extraccion_ok for e, o in pares)
    oculto = sum(bool(e.texto_oculto) == bool(o.texto_oculto) for e, o in pares)
    return Reporte(
        n=n,
        acierto={c: (n - len(fallos[c])) / n if n else 0.0 for c in CAMPOS},
        fallos=fallos,
        extraccion_ok_correcta=ok / n if n else 0.0,
        texto_oculto_correcto=oculto / n if n else 0.0,
    )


def main(argv: list[str] | None = None) -> int:
    from extraccion import extractores_por_defecto, extraer

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--salida", type=Path, help="guarda el reporte en JSON")
    args = parser.parse_args(argv)

    raiz = Path(__file__).resolve().parent.parent
    a, b = extractores_por_defecto()
    print(f"Extractor A: {a.nombre} · Extractor B: {b.nombre}\n")

    pares, detalle = [], []
    for ruta_json in sorted((raiz / "datos/facturas_json").glob("*.json")):
        esperado = FacturaCanonica.model_validate_json(ruta_json.read_text(encoding="utf-8"))
        inicio = time.monotonic()
        obtenido = extraer(raiz / esperado.archivo, esperado.canal, extractor_a=a, extractor_b=b)
        ms = int((time.monotonic() - inicio) * 1000)
        pares.append((esperado, obtenido))
        detalle.append({"archivo": esperado.archivo, "ms": ms, "extraccion_ok": obtenido.extraccion_ok,
                        "diferencias": obtenido.diferencias})
        marca = "ok " if obtenido.extraccion_ok == esperado.extraccion_ok else "MAL"
        print(f"[{marca}] {esperado.archivo:<45} {ms:>6} ms  {'; '.join(obtenido.diferencias)[:90]}")

    reporte = medir(pares)
    reporte.detalle = detalle
    print("\n" + reporte.como_texto())
    if args.salida:
        args.salida.write_text(json.dumps(reporte.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
