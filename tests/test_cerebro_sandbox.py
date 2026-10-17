"""Dev 2 · G3: Policy Sandbox de solo lectura (¿qué pasaría con otros límites?)."""

from __future__ import annotations

import pytest
from cerebro_util import factura, nueva_cerebro
from conftest import RAIZ

from cerebro.semantica import CapaFija


def huella_db(c) -> tuple:
    with c.db.transaccion() as con:
        return (con.execute("SELECT group_concat(hash) FROM decision_log").fetchone()[0],
                con.execute("SELECT COUNT(*), SUM(monto_usd_cents) FROM pagos").fetchone(),
                con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0],
                con.execute("SELECT COUNT(*) FROM reglas_versiones").fetchone()[0])


def test_subir_el_limite_por_pago_cambia_la_12(tmp_path):
    s = nueva_cerebro(tmp_path).simular_politica(factura("12"), {"limite_pago_usd": 8000})
    assert s["modo"] == "SANDBOX" and "no se ejecutó ningún pago" in s["advertencia"]
    assert (s["original"]["decision"], s["simulada"]["decision"]) == ("ESCALAR", "PAGAR")
    assert s["cambia_resultado"] is True
    assert {"regla": "limite_pago", "antes": "falla", "despues": "cumple"} in s["reglas_que_cambiaron"]
    assert s["cambios"] == {"limite_pago_usd": {"antes": "5000", "despues": "8000"}}
    assert "limite_pago" in s["razon"] and "ESCALAR" in s["razon"] and "PAGAR" in s["razon"]


def test_mas_saldo_no_basta_para_la_13(tmp_path):
    s = nueva_cerebro(tmp_path).simular_politica(factura("13"), {"saldo_disponible_usd": 40000})
    assert (s["original"]["decision"], s["simulada"]["decision"]) == ("FRENAR", "ESCALAR")
    assert {"regla": "saldo", "antes": "falla", "despues": "cumple"} in s["reglas_que_cambiaron"]
    assert "limite_pago" in s["simulada"]["reglas_fallidas"]


def test_endurecer_tambien_se_puede_simular(tmp_path):
    s = nueva_cerebro(tmp_path).simular_politica(factura("01"), {"limite_pago_usd": 100})
    assert (s["original"]["decision"], s["simulada"]["decision"]) == ("PAGAR", "ESCALAR")
    assert {"regla": "limite_pago", "antes": "cumple", "despues": "falla"} in s["reglas_que_cambiaron"]


def test_ningun_limite_desarma_un_veto_de_agente(tmp_path):
    s = nueva_cerebro(tmp_path).simular_politica(
        factura("14"), {"limite_pago_usd": 1_000_000, "tope_duro_usd": 1_000_000, "saldo_disponible_usd": 1_000_000})
    assert s["original"]["decision"] == s["simulada"]["decision"] == "FRENAR"
    assert s["cambia_resultado"] is False and "Texto oculto" in s["razon"]


def test_por_factura_id_usa_la_factura_registrada(tmp_path):
    c = nueva_cerebro(tmp_path)
    d = c.decidir(factura("12"))
    s = c.simular_politica(d.factura_id, {"limite_pago_usd": 8000})
    assert s["decision_registrada"]["hash"] == d.hash and s["simulada"]["decision"] == "PAGAR"
    with pytest.raises(LookupError):
        c.simular_politica("no-existe", {"limite_pago_usd": 1})


def test_sin_efectos_secundarios(tmp_path):
    c = nueva_cerebro(tmp_path)
    for n in ["01", "12", "13"]:
        c.decidir(factura(n))
    reglas_antes = (RAIZ / "reglas.yaml").read_bytes()
    antes = huella_db(c)
    for n in ["01", "07", "12", "13", "14"]:
        c.simular_politica(factura(n), {"limite_pago_usd": 50000, "saldo_disponible_usd": 90000,
                                        "tolerancia_contrato": 0.5})
    assert huella_db(c) == antes
    assert (RAIZ / "reglas.yaml").read_bytes() == reglas_antes
    assert c.verificar_cadena() == (True, None)


def test_no_llama_a_la_capa_semantica(tmp_path):
    capa = CapaFija()
    nueva_cerebro(tmp_path, capa=capa).simular_politica(factura("03"), {"limite_pago_usd": 1})
    assert capa.llamadas == []


@pytest.mark.parametrize("cambios", [
    {"limite_mensual": 1},
    {"limite_pago_usd": -1},
    {"limite_pago_usd": float("nan")},
    {"limite_pago_usd": True},
    {"tolerancia_contrato": 1.5},
    {"ventana_duplicados_dias": 2.5},
    {},
])
def test_cambios_invalidos(tmp_path, cambios):
    with pytest.raises(ValueError):
        nueva_cerebro(tmp_path).simular_politica(factura("01"), cambios)
