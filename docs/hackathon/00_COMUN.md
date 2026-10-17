# 00 · Común para todo el equipo

**Proyecto:** "Róbale a mi agente" · Reto Blinka · Hackathon 30X
**Entrega:** 18 de octubre · **Demo Day:** 19–20 de octubre

> Lean este archivo los tres antes de separarse. Todo lo que está aquí es un **contrato**: no se cambia sin avisar a los otros dos.

---

## 1. Qué construimos (en 5 líneas)

1. Llega una factura (Telegram, carga web, `.eml` o chat).
2. Se extrae a **quién**, **cuánto**, **moneda**, **cuándo** y las **líneas**.
3. Cinco agentes la revisan en paralelo y **solo pueden endurecer** la decisión.
4. Un motor de reglas determinista (Cedar o Python) es **lo único que puede decir PAGAR**.
5. Resultado: **PAGAR / ESCALAR / FRENAR** + explicación en español + registro encadenado por hash.

### Los 3 principios que nadie rompe

| # | Principio | Qué significa en código |
|---|---|---|
| 1 | Los modelos detectan, la regla decide, el humano firma | Ningún LLM, VLM ni Jev devuelve `PAGAR`. Solo emiten `Hallazgo`. |
| 2 | Veto monotónico | Severidad `0 PAGAR`, `1 ESCALAR`, `2 FRENAR`. Decisión = `max(...)`. Nada baja la severidad. |
| 3 | Fail-closed | Excepción, timeout, JSON inválido o desacuerdo → `ESCALAR`. |

> **Aprobar un pago indebido descalifica.** Si dudas, escala.

---

## 2. Quién hace qué

| Dev | Rol | Carpeta | Entrega principal |
|---|---|---|---|
| **Dev 1** | Datos y extracción | `/extraccion`, `/datos` | `extraer(ruta, canal) -> FacturaCanonica` |
| **Dev 2** | Cerebro de decisión (integrador del repo) | `/cerebro` | `decidir(factura) -> Decision` |
| **Dev 3** | Experiencia y demo | `/app` | La demo funcionando de punta a punta |

Cada uno tiene su archivo: `DEV1_datos_extraccion.md`, `DEV2_cerebro_decision.md`, `DEV3_experiencia_demo.md`.

---

## 3. Hora 0–1: los tres juntos

- [ ] Crear el repo **público** (regla del hackathon) con la estructura de abajo.
- [ ] Copiar `schemas.py` (sección 5) y `reglas.yaml` (sección 6) tal cual.
- [ ] Crear `.env.example` con las claves (sección 7). Nadie sube `.env`.
- [ ] Cada uno instala el entorno: `uv sync` (Python 3.12, en WSL2 quien use Windows).
- [ ] Probar que cada uno tiene acceso a su API (Gemini, segundo extractor, Jev, Telegram).
- [ ] Acordar quién duerme en qué turno (sección 9).

### Estructura del repo

```
/
├── schemas.py            ← contrato común (no tocar sin avisar)
├── reglas.yaml           ← reglas de Andes Labs LLC
├── pyproject.toml
├── .env.example
├── README.md             ← Dev 3 lo completa al final
├── datos/                ← Dev 1
│   ├── facturas/         (PDF, PNG, .eml, .txt)
│   ├── facturas_json/    (FacturaCanonica escrita a mano, una por factura)
│   ├── proveedores.yaml
│   ├── contratos.yaml
│   ├── historico_pagos.csv
│   ├── tasas_fx.yaml
│   └── ground_truth.csv
├── extraccion/           ← Dev 1
├── cerebro/              ← Dev 2
├── app/                  ← Dev 3 (Streamlit, FastAPI, Telegram)
└── tests/
```

---

## 4. Interfaces entre módulos

```python
# Dev 1
from extraccion import extraer
factura: FacturaCanonica = extraer(ruta: Path, canal: str)

# Dev 2
from cerebro import decidir, reanudar, verificar_cadena
decision: Decision = decidir(factura)                       # puede quedar en ESCALAR pendiente
decision: Decision = reanudar(factura_id, aprobado: bool, aprobador: str)
ok, fila_rota = verificar_cadena()                          # (True, None) si está íntegra

# Dev 3 consume las tres anteriores desde la API y la UI
```

**Regla de oro para no bloquearse:** hasta la hora 8, Dev 2 usa los JSON de `datos/facturas_json/` y Dev 3 usa decisiones falsas en `app/mock/decisiones.json`. Nadie espera a nadie.

---

## 5. `schemas.py` (copiar tal cual)

```python
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

Canal = Literal["telegram", "web", "email", "chat"]
Severidad = Literal[0, 1, 2]                       # 0 PAGAR, 1 ESCALAR, 2 FRENAR
DecisionTipo = Literal["PAGAR", "ESCALAR", "FRENAR"]


class Linea(BaseModel):
    descripcion: str
    cantidad: float
    precio_unitario: float
    total: float


class FacturaCanonica(BaseModel):
    id_documento: str                              # SHA-256 del archivo original
    archivo: str                                   # ruta relativa al original
    canal: Canal
    proveedor: str
    id_fiscal: str | None = None
    cuenta_bancaria: str | None = None
    numero_factura: str
    fecha_emision: date
    fecha_vencimiento: date | None = None
    moneda: str                                    # ISO 4217: COP, MXN, ARS, PEN, USD
    lineas: list[Linea]
    subtotal: float
    impuestos: float = 0.0
    total: float
    referencia_contrato: str | None = None
    texto_libre: str = ""                          # cuerpo del correo o mensaje de chat
    texto_oculto: list[str] = Field(default_factory=list)   # del escáner
    extraccion_ok: bool = True
    diferencias: list[str] = Field(default_factory=list)    # A vs B, aritmética


class Hallazgo(BaseModel):
    agente: str                                    # "duplicados", "contrato", ...
    severidad: Severidad
    probabilidad: float | None = None              # de Jev, si aplica
    motivo: str                                    # frase en español, legible
    evidencia: str = ""
    campo: str | None = None
    latencia_ms: int = 0


class Decision(BaseModel):
    factura_id: str
    numero_factura: str
    proveedor: str
    decision: DecisionTipo
    estado: Literal["final", "pendiente_humano"] = "final"
    explicacion: str
    contrafactual: str | None = None
    hallazgos: list[Hallazgo]
    cedar: Literal["ALLOW", "DENY"]
    monto_original: float
    moneda: str
    monto_usd: float
    fx_rate: float
    fx_source: str
    version_reglas: str
    aprobador: str | None = None
    aprobado: bool | None = None
    ts: datetime
    hash_prev: str
    hash: str
```

---

## 6. `reglas.yaml` (empresa ficticia Andes Labs LLC, Delaware)

```yaml
empresa: Andes Labs LLC
moneda_base: USD
limite_pago_usd: 5000            # hasta aquí paga solo
tope_duro_usd: 15000             # por encima: FRENAR siempre, ni con humano
limite_mensual_proveedor_usd: 10000
limite_mensual_global_usd: 40000
saldo_disponible_usd: 25000
tolerancia_contrato: 0.05        # 5 % en precio o cantidad por línea
tolerancia_fx: 0.03              # desviación vs tasa del contrato
umbral_sospecha: 0.25            # prob. de Jev desde la que se escala
ventana_duplicados_dias: 15
tolerancia_monto_duplicado: 0.02
```

---

## 7. `.env.example`

```
GEMINI_API_KEY=
OPENAI_API_KEY=            # o ANTHROPIC_API_KEY si el extractor B es Claude Haiku 5.5
TYPESAFE_API_KEY=          # Jev (o VERCEL_AI_GATEWAY_KEY / OPENROUTER_API_KEY)
TELEGRAM_BOT_TOKEN=
TELEGRAM_APROBADORES=      # chat_ids separados por coma
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
SIGNING_KEY_PATH=./firma_ed25519.pem
DEMO_CACHE=0               # 1 = responde desde caché para la demo
DB_PATH=./blinka.db
```

---

## 8. Matriz de decisión (la misma para todos)

Precedencia **FRENAR > ESCALAR > PAGAR**. PAGAR solo si `extraccion_ok` y Cedar `ALLOW` y cero hallazgos.

| Disparador | Decisión |
|---|---|
| Todo en regla | PAGAR |
| Duplicado exacto (mismo número + proveedor + monto) | FRENAR |
| Duplicado disfrazado (otro número, monto ±2 %, fecha ±15 días) | ESCALAR |
| Proveedor nuevo no permitido | ESCALAR |
| Proveedor bloqueado | FRENAR |
| Cuenta bancaria distinta a la registrada | ESCALAR (prioridad alta) |
| Línea fuera de tolerancia del contrato o sin ítem | ESCALAR |
| Monto > USD 5.000 y ≤ USD 15.000 | ESCALAR |
| Monto > USD 15.000 o excede límite mensual | FRENAR |
| Saldo insuficiente | FRENAR |
| Texto oculto o instrucciones al sistema | FRENAR + alerta |
| Extracción dudosa (A ≠ B, no suma) | ESCALAR |
| Error técnico o timeout | ESCALAR |

---

## 9. Cronograma y puntos de integración

| Hora | Hito | Quién |
|---|---|---|
| 0–1 | Repo, `schemas.py`, `reglas.yaml`, claves probadas | Los tres |
| 3 | **15 JSON a mano** en `datos/facturas_json/` → Dev 2 ya decide | Dev 1 → Dev 2 |
| 8 | **Integración 1:** factura real → `extraer` → `decidir` en consola | Dev 1 + Dev 2 |
| 14 | **Integración 2:** punta a punta en la UI con las 15 facturas y autonomía medida | Los tres |
| 18–23 | Descanso **por turnos** (nunca los tres a la vez) | Los tres |
| 20 | Telegram en vivo + aprobación humana funcionando | Dev 3 + Dev 2 |
| 24 | **Congelar funcionalidades.** Solo arreglos | Los tres |
| 24–30 | Correr el set, medir, grabar video, ensayar el pitch 3 veces | Los tres |

### Reglas de equipo

- Commits pequeños a `main` cada 1–2 horas. Nada de ramas largas.
- `schemas.py` y `reglas.yaml` no se tocan sin avisar.
- En cada hito: reunión de 5 minutos → qué funciona, qué está bloqueado, qué se recorta.
- **Ningún dato real** en el repo: empresas, personas y cuentas inventadas.

### Lo que nunca se recorta

Cero pagos indebidos · explicación legible por decisión · autonomía medida contra `ground_truth.csv`.
