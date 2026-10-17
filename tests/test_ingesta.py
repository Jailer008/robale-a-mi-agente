from __future__ import annotations

import hashlib

import pytest

from conftest import RAIZ, cargar_factura_json
from extraccion.ingesta import IngestaError, ingerir, sha256_archivo

PNG = b"\x89PNG\r\n\x1a\n"


def ruta(nombre: str):
    return RAIZ / "datos" / "facturas" / nombre


@pytest.mark.parametrize("n", [f"{i:02d}" for i in range(1, 16)])
def test_id_documento_es_el_sha256_del_original(n):
    esperado = cargar_factura_json(n)
    doc = ingerir(RAIZ / esperado.archivo)
    assert doc.id_documento == esperado.id_documento
    assert doc.archivo == esperado.archivo


def test_sha256_archivo(tmp_path):
    archivo = tmp_path / "x.txt"
    archivo.write_bytes(b"hola")
    assert sha256_archivo(archivo) == hashlib.sha256(b"hola").hexdigest()


def test_pdf_se_rasteriza_y_conserva_su_texto():
    doc = ingerir(ruta("01_limpia.pdf"))
    assert doc.tipo == "pdf"
    assert len(doc.imagenes) == 1 and doc.imagenes[0].startswith(PNG)
    assert doc.mime_imagen == "image/png"
    assert "NS-2026-0145" in doc.texto
    assert doc.pdf is not None and doc.pdf.startswith(b"%PDF")
    assert doc.texto_libre == ""
    assert doc.avisos == ()


@pytest.mark.parametrize("n, archivo", [("03", "03_limpia.eml"), ("10", "10_cambio_cuenta.eml")])
def test_eml_cuerpo_a_texto_libre_y_adjunto_como_factura(n, archivo):
    doc = ingerir(ruta(archivo))
    esperado = cargar_factura_json(n)
    assert doc.texto_libre.strip() == esperado.texto_libre.strip()
    assert doc.tipo == "pdf"
    assert doc.pdf is not None and doc.imagenes[0].startswith(PNG)
    assert esperado.numero_factura in doc.texto
    # El hash es del .eml completo, no del adjunto.
    assert doc.id_documento == esperado.id_documento


def test_eml_sin_adjunto_usa_el_cuerpo_como_factura(tmp_path):
    archivo = tmp_path / "solo_texto.eml"
    archivo.write_bytes(
        b"From: a@b.example\r\nTo: c@d.example\r\nSubject: Factura\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nFactura F-1 total USD 100\r\n"
    )
    doc = ingerir(archivo)
    assert doc.tipo == "texto"
    assert "F-1" in doc.texto and "F-1" in doc.texto_libre
    assert doc.imagenes == () and doc.pdf is None


def test_chat_txt():
    doc = ingerir(ruta("04_limpia_chat.txt"))
    esperado = cargar_factura_json("04")
    assert doc.tipo == "texto"
    assert doc.texto_libre == esperado.texto_libre
    assert doc.texto == esperado.texto_libre
    assert doc.imagenes == ()


def test_png_se_pasa_tal_cual_y_esta_nitida():
    original = ruta("02_limpia.png").read_bytes()
    doc = ingerir(ruta("02_limpia.png"))
    assert doc.tipo == "imagen"
    assert doc.imagenes == (original,)
    assert doc.mime_imagen == "image/png"
    assert doc.avisos == ()


def test_jpg_borrosa_genera_aviso():
    doc = ingerir(ruta("15_borrosa.jpg"))
    assert doc.mime_imagen == "image/jpeg"
    assert any("borrosa" in aviso for aviso in doc.avisos)


@pytest.mark.parametrize(
    "nombre, contenido",
    [("factura.docx", b"PK\x03\x04"), ("roto.pdf", b"esto no es un pdf"), ("roto.png", b"nada")],
)
def test_entradas_invalidas_lanzan_ingesta_error(tmp_path, nombre, contenido):
    archivo = tmp_path / nombre
    archivo.write_bytes(contenido)
    with pytest.raises(IngestaError):
        ingerir(archivo)


def test_archivo_inexistente(tmp_path):
    with pytest.raises(IngestaError):
        ingerir(tmp_path / "no_existe.pdf")
