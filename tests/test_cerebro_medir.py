"""Dev 2 · G3: python -m cerebro.medir y el contrato de resultados.json (sin APIs)."""

from __future__ import annotations

import json

import pytest

from cerebro import medir as modulo_medir
from cerebro.medir import Resultados, main, medir


@pytest.fixture(scope="module")
def mock(tmp_path_factory):
    return medir("MOCK", directorio=tmp_path_factory.mktemp("mock"))


def test_mock_15_de_15_sin_falsos_pagar(mock):
    r = mock.resumen
    assert (r.total, r.aciertos, r.falsos_pagar) == (15, 15, 0)
    assert r.exactitud == 1.0
    assert r.autonomas == 9 and r.autonomia == pytest.approx(0.6)      # 6 PAGAR + 3 FRENAR sin humano
    assert r.pendientes_humano == 6
    assert (r.jurado_aciertos, r.jurado_total) == (6, 6)


def test_matriz_de_confusion(mock):
    assert mock.matriz.etiquetas == ["PAGAR", "ESCALAR", "FRENAR"]
    assert mock.matriz.filas == {"PAGAR": {"PAGAR": 6, "ESCALAR": 0, "FRENAR": 0},
                                 "ESCALAR": {"PAGAR": 0, "ESCALAR": 6, "FRENAR": 0},
                                 "FRENAR": {"PAGAR": 0, "ESCALAR": 0, "FRENAR": 3}}


def test_autonomia_por_factura(mock):
    por_numero = {f.numero: f for f in mock.facturas}
    assert por_numero["01"].autonoma and por_numero["13"].autonoma
    assert not por_numero["12"].autonoma and por_numero["12"].estado == "pendiente_humano"
    assert all(f.fuente == "json" for f in mock.facturas)
    assert por_numero["14"].responsable["nombre"] == "seguridad"


def test_modo_y_costo_honestos(mock):
    assert mock.modo == "MOCK" and "JSON" in mock.descripcion_modo
    assert mock.capa_semantica == "determinista"
    assert mock.costo.medido is False and mock.costo.usd_total is None and mock.costo.usd_por_factura is None
    assert mock.costo.motivo


def test_latencia_por_etapa(mock):
    assert {"agentes_ms", "revalidacion_ms", "total_ms"} <= set(mock.latencia)
    assert "extraccion_ms" not in mock.latencia                          # en MOCK no hay extracción
    etapa = mock.latencia["total_ms"]
    assert etapa.n == 15 and etapa.max_ms >= etapa.p50_ms >= 0
    assert all("total_ms" in f.latencia_ms for f in mock.facturas)


def test_integridad_del_registro(mock):
    i = mock.integridad
    assert i.cadena_integra and i.fila_rota is None and i.firmada and i.pagos_integros and i.problemas_pagos == []


def test_resultados_json_es_estable(mock, tmp_path):
    ruta = tmp_path / "resultados.json"
    ruta.write_text(mock.model_dump_json(indent=2), encoding="utf-8")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["version_contrato"] == "1.0"
    assert Resultados.model_validate(datos) == mock


def test_cache_reproducible_y_sin_llamadas(tmp_path):
    a = medir("CACHÉ", directorio=tmp_path / "a")
    b = medir("CACHÉ", directorio=tmp_path / "b")
    assert a.resumen.aciertos == 15 and a.resumen.falsos_pagar == 0
    assert all(f.fuente == "cache" for f in a.facturas)
    assert "extraccion_ms" in a.latencia
    clave = [(f.numero, f.obtenido, f.explicacion) for f in a.facturas]
    assert clave == [(f.numero, f.obtenido, f.explicacion) for f in b.facturas]
    assert a.costo.medido is False and a.costo.usd_total is None


def test_live_exige_confirmacion(tmp_path, monkeypatch):
    with pytest.raises(PermissionError):
        medir("LIVE", directorio=tmp_path)
    monkeypatch.setenv("DEMO_CACHE", "1")
    with pytest.raises(ValueError):
        medir("LIVE", directorio=tmp_path, confirmar_costo=True)


def test_cli_escribe_resultados(tmp_path, capsys):
    salida = tmp_path / "r.json"
    assert main(["--modo", "mock", "--salida", str(salida)]) == 0
    assert Resultados.model_validate_json(salida.read_text(encoding="utf-8")).resumen.falsos_pagar == 0
    texto = capsys.readouterr().out
    assert "Pagos indebidos: 0" in texto and "MOCK" in texto


def test_cli_falla_si_hay_falsos_pagar(tmp_path, monkeypatch):
    original = modulo_medir.Cerebro.decidir_con_traza

    def todo_pagar(self, factura):
        d, traza = original(self, factura)
        return d.model_copy(update={"decision": "PAGAR", "estado": "final"}), traza

    monkeypatch.setattr(modulo_medir.Cerebro, "decidir_con_traza", todo_pagar)
    assert main(["--modo", "mock", "--salida", str(tmp_path / "r.json")]) == 1
