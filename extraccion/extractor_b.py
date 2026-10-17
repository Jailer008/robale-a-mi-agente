"""Extractor B: Claude Haiku 5.5 con salida estructurada (otro proveedor que A).

Proveedor distinto para que los errores de A y B no estén correlacionados.
"""

from __future__ import annotations

import base64
from typing import Any

import anthropic

from extraccion.ingesta import Documento
from extraccion.modelo import PROMPT, CamposExtraidos, ErrorExtraccion, texto_de_apoyo

MODELO = "claude-haiku-5-5"


class ExtractorClaude:
    def __init__(self, *, modelo: str = MODELO, timeout_s: float = 20.0, cliente: Any = None) -> None:
        self.modelo = modelo
        self.timeout_s = timeout_s
        self._cliente = cliente
        self.nombre = f"B:{modelo}"

    @property
    def cliente(self) -> Any:
        if self._cliente is None:
            # La clave se lee de ANTHROPIC_API_KEY dentro del SDK. Sin reintentos: el
            # orquestador ya aplica un timeout total y escala si se agota.
            self._cliente = anthropic.Anthropic(max_retries=0)
        return self._cliente

    def __call__(self, doc: Documento) -> CamposExtraidos:
        contenido: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": doc.mime_imagen,
                    "data": base64.standard_b64encode(img).decode("ascii"),
                },
            }
            for img in doc.imagenes
        ]
        contenido.append({"type": "text", "text": texto_de_apoyo(doc)})

        respuesta = self.cliente.messages.parse(
            model=self.modelo,
            max_tokens=8000,
            system=PROMPT,
            messages=[{"role": "user", "content": contenido}],
            output_config={"effort": "low"},
            output_format=CamposExtraidos,
            timeout=self.timeout_s,
        )
        if respuesta.stop_reason == "refusal":
            raise ErrorExtraccion(f"{self.nombre} rechazó la solicitud")
        if respuesta.parsed_output is None:
            raise ErrorExtraccion(f"{self.nombre} no devolvió datos estructurados")
        return respuesta.parsed_output
