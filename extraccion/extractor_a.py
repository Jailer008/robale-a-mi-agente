"""Extractor A: Gemini con salida estructurada. La entrada principal es la imagen."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from extraccion.ingesta import Documento
from extraccion.modelo import PROMPT, CamposExtraidos, ErrorExtraccion, esquema_plano, texto_de_apoyo

MODELO_POR_DEFECTO = "gemini-3.8-flash"


class ExtractorGemini:
    def __init__(
        self,
        *,
        modelo: str | None = None,
        prompt: str = PROMPT,
        timeout_s: float = 20.0,
        cliente: Any = None,
        etiqueta: str = "A",
    ) -> None:
        self.modelo = modelo or os.environ.get("GEMINI_MODEL") or MODELO_POR_DEFECTO
        self.prompt = prompt
        self.timeout_s = timeout_s
        self._cliente = cliente
        self.nombre = f"{etiqueta}:{self.modelo}"

    @property
    def cliente(self) -> Any:
        if self._cliente is None:
            # La clave se lee de GEMINI_API_KEY dentro del SDK; nunca pasa por nuestro código.
            self._cliente = genai.Client(
                http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000))
            )
        return self._cliente

    def __call__(self, doc: Documento) -> CamposExtraidos:
        partes = [types.Part.from_bytes(data=img, mime_type=doc.mime_imagen) for img in doc.imagenes]
        partes.append(types.Part.from_text(text=texto_de_apoyo(doc)))
        respuesta = self.cliente.models.generate_content(
            model=self.modelo,
            contents=partes,
            config=types.GenerateContentConfig(
                system_instruction=self.prompt,
                response_mime_type="application/json",
                response_json_schema=esquema_plano(),
                temperature=0,
            ),
        )
        if not respuesta.text:
            raise ErrorExtraccion(f"{self.nombre} devolvió una respuesta vacía")
        try:
            return CamposExtraidos.model_validate_json(respuesta.text)
        except ValidationError as error:
            raise ErrorExtraccion(f"{self.nombre} devolvió JSON inválido") from error
