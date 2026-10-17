"""Firma Ed25519 de cada fila del registro (`cryptography`).

La clave privada vive en SIGNING_KEY_PATH (PEM PKCS#8, fuera del repo: `*.pem` está en
.gitignore). Si no existe, se genera una nueva. La verificación usa SIEMPRE la clave pública
derivada de esa clave local, nunca una guardada en la base: así quien edite la base no puede
re-firmar filas con una clave propia.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class Firmante:
    def __init__(self, privada: Ed25519PrivateKey) -> None:
        self._privada = privada
        self._publica = privada.public_key()
        crudo = self._publica.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.huella = hashlib.sha256(crudo).hexdigest()[:16]

    @classmethod
    def generar(cls) -> Firmante:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def desde_archivo(cls, ruta: Path, *, crear: bool = True) -> Firmante:
        ruta = Path(ruta)
        if not ruta.exists():
            if not crear:
                raise FileNotFoundError(f"No existe la clave de firma {ruta}")
            privada = Ed25519PrivateKey.generate()
            pem = privada.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
            ruta.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as archivo:
                archivo.write(pem)
            return cls(privada)
        privada = serialization.load_pem_private_key(ruta.read_bytes(), password=None)
        if not isinstance(privada, Ed25519PrivateKey):
            raise ValueError(f"{ruta} no es una clave Ed25519")
        return cls(privada)

    def firmar(self, sello: str) -> str:
        return self._privada.sign(sello.encode("ascii")).hex()

    def verificar(self, sello: str, firma: str) -> bool:
        try:
            self._publica.verify(bytes.fromhex(firma), sello.encode("ascii"))
        except (InvalidSignature, ValueError):
            return False
        return True

    def publica_pem(self) -> str:
        return self._publica.public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
