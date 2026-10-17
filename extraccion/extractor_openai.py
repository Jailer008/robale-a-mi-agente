"""Extractor OpenAI: GPT-6 Luna con salida estructurada (Responses API)."""

from __future__ import annotations

import base64
import os
from typing import Any

import openai

from extraccion.ingesta import Documento
from extraccion.modelo import PROMPT, CamposExtraidos, ErrorExtraccion, texto_de_apoyo

MODELO_POR_DEFECTO = "gpt-6-luna"


class ExtractorOpenAI:
    def __init__(
        self,
        *,
        modelo: str | None = None,
        prompt: str = PROMPT,
        timeout_s: float = 20.0,
        cliente: Any = None,
        etiqueta: str = "A",
    ) -> None:
        self.modelo = modelo or os.environ.get("OPENAI_MODEL") or MODELO_POR_DEFECTO
        self.prompt = prompt
        self.timeout_s = timeout_s
        self._cliente = cliente
        self.nombre = f"{etiqueta}:{self.modelo}"

    @property
    def cliente(self) -> Any:
        if self._cliente is None:
            # La clave se lee de OPENAI_API_KEY dentro del SDK. Sin reintentos: el
            # orquestador ya aplica un timeout total y escala si se agota.
            self._cliente = openai.OpenAI(max_retries=0)
        return self._cliente

    def __call__(self, doc: Documento) -> CamposExtraidos:
        contenido: list[dict[str, Any]] = [
            {
                "type": "input_image",
                "image_url": f"data:{doc.mime_imagen};base64,{base64.standard_b64encode(img).decode('ascii')}",
                "detail": "high",
            }
            for img in doc.imagenes
        ]
        contenido.append({"type": "input_text", "text": texto_de_apoyo(doc)})

        respuesta = self.cliente.responses.parse(
            model=self.modelo,
            instructions=self.prompt,
            input=[{"role": "user", "content": contenido}],
            text_format=CamposExtraidos,
            timeout=self.timeout_s,
        )
        if respuesta.output_parsed is None:
            raise ErrorExtraccion(f"{self.nombre} no devolvió datos estructurados (posible rechazo)")
        return respuesta.output_parsed
