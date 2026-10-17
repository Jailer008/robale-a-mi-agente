from __future__ import annotations

from conftest import cargar_factura_json
from extraccion.medir import CAMPOS, medir


def test_todo_correcto_da_100_por_ciento():
    pares = [(cargar_factura_json(n), cargar_factura_json(n)) for n in ("01", "02", "03")]
    reporte = medir(pares)
    assert reporte.n == 3
    assert all(reporte.acierto[c] == 1.0 for c in CAMPOS)
    assert reporte.extraccion_ok_correcta == 1.0
    assert reporte.texto_oculto_correcto == 1.0


def test_un_total_mal_leido_baja_ese_campo():
    bien = cargar_factura_json("01")
    mal = bien.model_copy(update={"total": 2000.0, "proveedor": "NUBIA STUDIO S.A.S."})
    reporte = medir([(bien, bien), (bien, mal)])
    assert reporte.acierto["total"] == 0.5
    assert reporte.acierto["proveedor"] == 1.0          # normalizado: es el mismo
    assert reporte.fallos["total"] == ["datos/facturas/01_limpia.pdf"]


def test_lineas_se_comparan_por_cantidad_y_totales():
    bien = cargar_factura_json("06")
    sin_una = bien.model_copy(update={"lineas": bien.lineas[:-1]})
    assert medir([(bien, sin_una)]).acierto["lineas"] == 0.0


def test_detecta_si_la_borrosa_no_se_marco():
    esperado = cargar_factura_json("15")
    obtenido = esperado.model_copy(update={"extraccion_ok": True, "diferencias": []})
    assert medir([(esperado, obtenido)]).extraccion_ok_correcta == 0.0


def test_tabla_imprimible():
    bien = cargar_factura_json("01")
    texto = medir([(bien, bien)]).como_texto()
    assert "total" in texto and "100" in texto
