# Cerebro de decisión (Dev 2): contrato para Dev 3

`decidir(factura)` convierte una `FacturaCanonica` en una `Decision`: **PAGAR**, **ESCALAR** o **FRENAR**, con explicación en español, hallazgos, datos FX, versión de reglas y registro encadenado por hash.

Tres principios:

- **Los modelos detectan, la regla decide, el humano firma.** Ningún agente ni modelo devuelve PAGAR.
- **Veto monotónico.** La decisión es `max(reglas, hallazgos, fallos)`. Nada baja la severidad.
- **Fail-closed.** Excepción, timeout, dato faltante o desacuerdo dan como mínimo ESCALAR.

> **Pagos SIMULADOS.** No hay conexión bancaria. PAGAR es una autorización simulada que se anota en la tabla `pagos`; no es una transferencia. La UI debe decirlo así.

Para comprobar el contrato sin APIs ni claves:

```bash
uv run pytest tests/test_contrato_cerebro.py -q
```

## Qué está validado y qué no

| Componente | Estado |
|---|---|
| Reglas, cinco agentes deterministas, agregador, contrafactual | Probado (pytest) |
| Registro encadenado y firma Ed25519 | Probado |
| `reanudar` (idempotencia y concurrencia) | Probado |
| Sandbox | Probado |
| `medir` en modos MOCK y CACHÉ | Probado. 15/15 decisiones correctas, 0 pagos indebidos |
| Capa semántica MOCK (`CapaFija`) | Solo para pruebas. **No es un modelo** |
| Capa semántica LLM (`CapaClaude`, `CEREBRO_SEMANTICA=claude`) | Probada con cliente falso. **SIN VALIDAR** con la API real |
| Jev `typesafe/jev-1.13` vía OpenRouter (`CapaJev`, `CEREBRO_SEMANTICA=jev`) | Implementado con el esquema oficial de la Decisions API (`noul` y `choice`). Probado con transporte falso. La validación LIVE queda pendiente de autorización |
| `medir --modo live` | Implementado. **SIN VALIDAR**: requiere modelos de pago |

## 1. Funciones públicas

```python
from cerebro import (decidir, decidir_async, reanudar, verificar_cadena,
                     paquete_evidencia, simular_politica, CadenaAlterada, ReevaluacionNecesaria)
```

| Función | Qué hace |
|---|---|
| `decidir(factura) -> Decision` | **Nunca lanza.** ESCALAR deja `estado="pendiente_humano"`. Se puede llamar desde código síncrono o desde un event loop (FastAPI/Streamlit). |
| `await decidir_async(factura) -> Decision` | La misma función, para endpoints `async`. |
| `reanudar(factura_id, aprobado, aprobador, *, clave_idempotencia=None) -> Decision` | Resuelve un ESCALAR pendiente. Ver la sección 5. |
| `verificar_cadena() -> (bool, int \| None)` | Devuelve `(True, None)` si la cadena está íntegra, o `(False, id_fila)` con la primera fila alterada. Si hay clave configurada, verifica también las firmas. |
| `paquete_evidencia(factura_id) -> dict` | Solo lectura. Reúne la decisión inicial y la resolución humana, la factura, el texto exacto de las reglas usadas, el documento original contra su SHA-256, las firmas, los eventos, el pago simulado y el `responsable` del veto (regla, agente o persona). |
| `simular_politica(factura \| factura_id, cambios) -> dict` | **Policy Sandbox** de solo lectura (ver la sección 9). |

`factura_id` es el `id_documento`, es decir, el SHA-256 del original. Es el `{factura_id}` de `/aprobar/{factura_id}`.

Las funciones del módulo usan una instancia compartida que se configura con variables de entorno (sección 7). Para tests, crear `Cerebro(db_path=..., ...)`.

## 2. `Decision` y `Hallazgo`

Ambas vienen de `schemas.py`, que no se modifica.

**`Decision`**

| Campo | Significado |
|---|---|
| `factura_id` | SHA-256 del original. Si el archivo no se pudo leer: `sin-hash-…` |
| `numero_factura`, `proveedor` | Tal como se extrajeron |
| `decision` | `PAGAR` \| `ESCALAR` \| `FRENAR`. **Mostrar siempre este campo, no `cedar`** |
| `estado` | `final` o `pendiente_humano`. Solo ESCALAR queda pendiente |
| `explicacion` | Frase del motivo de mayor severidad, más "(y N motivos más)". En PAGAR: "Pago autorizado (simulado): …" |
| `contrafactual` | "Se habría pagado si …", o "Sin contrafactual: …" cuando no hay valor frontera. `None` en PAGAR |
| `hallazgos` | Lista de `Hallazgo`, de mayor a menor severidad. Las reglas aparecen como `agente="reglas"` |
| `cedar` | `ALLOW`/`DENY` de la **política de reglas**. Un `ALLOW` con hallazgos de agentes sigue sin pagar (casos 07, 08, 11, 14) |
| `monto_original`, `moneda` | Monto en la moneda de la factura |
| `monto_usd`, `fx_rate`, `fx_source` | `fx_rate` = unidades por USD. Sin tasa confiable: `0.0` y `"sin tasa FX confiable"` |
| `version_reglas` | SHA-256 de `reglas.yaml` usado |
| `aprobador`, `aprobado` | Autoridad humana en una resolución de `reanudar` |
| `ts` | UTC |
| `hash_prev`, `hash` | Cadena SHA-256 |
| `codigo_principal` | v2. Código estable del motivo principal (`OK` en PAGAR). **La pantalla grande muestra solo este código**, nunca texto de la factura |
| `aprobable` | v2. `True` solo si la decisión es ESCALAR, sin señales de severidad 2 y sin `EXTRACCION` ni `ERROR_TECNICO`. Es informativo: `reanudar` lo **recalcula** en el servidor |
| `accion_requerida` | v2. Qué hacer cuando no es aprobable (por ejemplo, verificar por teléfono), o `None` |

**`Hallazgo`**

| Campo | Significado |
|---|---|
| `agente` | Uno de `duplicados`, `contrato`, `beneficiario`, `seguridad`, `presupuesto`, `reglas`, `sistema`, `registro` |
| `severidad` | 1 = ESCALAR, 2 = FRENAR |
| `probabilidad` | Solo si lo aportó la capa semántica |
| `motivo` | Frase en español para el jurado |
| `evidencia` | Su prefijo indica el tipo de hallazgo (ver abajo) |
| `campo` | Campo de la factura implicado |
| `latencia_ms` | Tiempo del agente |
| `codigo` | v2. Código estable del hallazgo (ver sección 11) |

Tipos de hallazgo, según el prefijo de `evidencia` (`cerebro.tipos.tipo_de(h)`):

| Prefijo | Tipo | Significado |
|---|---|---|
| `[fallo_tecnico]` | Fallo técnico | El detector no pudo correr (excepción, timeout, servicio caído) |
| `[sin_evidencia]` | Sin evidencia | El detector corrió, pero faltan datos para concluir |
| Cualquier otro | Riesgo | Evidencia real de un problema |

Los hallazgos de la capa semántica llevan `[semantica:<nombre>]`.

## 3. Contrato de eventos (comité en vivo)

La tabla `eventos` está en la base `DB_PATH`. Hay una fila por agente y por decisión, más una fila `reglas` (la "llave") y, si la revalidación final detectó un problema, una fila `revalidacion`.

| Columna | Contenido |
|---|---|
| `id` | Autoincremental |
| `factura_id` | Igual que en `Decision` |
| `decision_id` | Fila de `decision_log` |
| `agente` | Agente que emitió el evento |
| `severidad` | 0, 1 o 2 |
| `probabilidad` | `null` si no hay capa semántica |
| `latencia_ms` | Tiempo del agente |
| `motivo` | Frase principal |
| `ts` | Momento del evento |
| `tipo` | `riesgo` \| `fallo_tecnico` \| `sin_evidencia` \| `sin_hallazgos` |

```sql
SELECT agente, severidad, probabilidad, latencia_ms, motivo, tipo
FROM eventos WHERE factura_id = ? ORDER BY id;
```

Los eventos se escriben junto con la decisión, en la misma transacción. El comité lee las filas por `factura_id`.

## 4. Contrato de `resultados.json` (versión 1.0)

```bash
uv run python -m cerebro.medir                    # MOCK (por defecto)
uv run python -m cerebro.medir --modo cache       # CACHÉ
uv run python -m cerebro.medir --modo live --confirmar-costo   # LIVE: cuesta dinero, SIN VALIDAR
uv run python -m cerebro.medir --modo cache --semantica jev --confirmar-costo   # CACHÉ + Jev en vivo (créditos de OpenRouter)
```

Escribe `resultados.json`; con `--salida` se cambia la ruta. El código de salida es **1 si hubo algún PAGAR indebido**. Cada corrida usa una base y una clave efímeras, así que nunca toca `blinka.db`. El modelo pydantic es `cerebro.medir.Resultados`.

| Campo | Contenido |
|---|---|
| `version_contrato` | `"1.0"` |
| `generado` | Fecha y hora de la corrida |
| `modo` | `MOCK` (JSON canónicos, sin extracción) \| `CACHÉ` (originales → `extraer()` solo desde `cache/`) \| `LIVE` |
| `descripcion_modo` | Texto que la UI debe mostrar junto a las métricas |
| `capa_semantica` | `determinista` \| `mock` \| `live` \| `no_disponible` |
| `capa_semantica_nombre` | Por ejemplo `jev:typesafe/jev-1.13`; `null` si no hay capa |
| `ref_date` | Fecha de referencia usada |
| `version_reglas` | SHA-256 de `reglas.yaml` |
| `ground_truth` | `v2` (por defecto, `cerebro/ground_truth_v2.csv`) o `v1` (`datos/ground_truth.csv` de Dev 1) |
| `resumen` | `total`, `aciertos`, `exactitud`, `falsos_pagar`, `autonomas`, `autonomia`, `pendientes_humano`, `jurado_aciertos`, `jurado_total` |
| `matriz` | `etiquetas` y `filas[esperado][obtenido]` (matriz 3×3) |
| `latencia` | Por etapa (`extraccion_ms`, `agentes_ms`, `agente.<nombre>_ms`, `revalidacion_ms`, `total_ms`), cada una con `n`, `promedio_ms`, `p50_ms`, `max_ms` |
| `costo` | `medido`, `usd_total`, `usd_por_factura`, `motivo`, `semantica_usd` y `semantica_llamadas` (costo real de Jev, tomado de `usage.cost`). **Si no se midió, es `null`, nunca 0.** La extracción no informa costo, por eso `usd_total` sigue en `null` |
| `integridad` | `cadena_integra`, `fila_rota`, `firmada`, `pagos_integros`, `problemas_pagos` |
| `facturas` | Por factura: `numero`, `archivo`, `jurado`, `esperado`, `obtenido`, `correcto`, `falso_pagar`, `autonoma`, `estado`, `explicacion`, `contrafactual`, `responsable`, `fuente` (`json`/`cache`/`cache_miss`/`live`), `factura_id`, `latencia_ms` |

**Autonomía** = facturas con decisión correcta y final, sin intervención humana, sobre el total. En el set: 9/15 = 60 % (6 PAGAR + 3 FRENAR).

## 5. Manejo de errores

| Llamada | Excepción | HTTP sugerido | Significado |
|---|---|---|---|
| `decidir` | Ninguna | — | Un error técnico da ESCALAR con la causa en `explicacion` (o FRENAR si ya se vio texto oculto) |
| `reanudar` | `LookupError` | 404 | No hay decisiones para ese `factura_id` |
| `reanudar` | `ValueError` | 409/400 | No está pendiente, ya fue resuelta por otra solicitud, falta el aprobador, o la `clave_idempotencia` se reutilizó con otros datos |
| `reanudar` | `PermissionError` | 403 | Aprobador fuera de la lista, o no hay lista configurada (en ese caso solo se puede **rechazar**) |
| `reanudar` | `CadenaAlterada` (`RuntimeError`) | 423 | El registro fue manipulado o hay una firma inválida: no se aprueba nada |
| `reanudar` | `ReevaluacionNecesaria` (`RuntimeError`) | 503 | Un detector falló al revalidar. La factura **sigue pendiente**: reintentar más tarde |
| `paquete_evidencia`, `simular_politica` | `LookupError` | 404 | `factura_id` desconocido |
| `simular_politica` | `ValueError` | 400 | Límite desconocido o fuera de rango |

Qué pasa al aprobar (`aprobado=True`). Todo se revalida en una transacción:

- **Sin aprobación posible → FRENAR final:**
  - severidad 2 (tope duro, saldo, límite mensual, duplicado exacto, texto oculto o inyección, proveedor bloqueado);
  - extracción, FX o datos no validados, o hallazgo `sin_evidencia`. El texto dice "Corrija la entrada y vuelva a enviarla".
- **Fallo técnico → `ReevaluacionNecesaria`.** No se escribe nada.
- **En cualquier otro caso → PAGAR simulado**, con `aprobador`, y queda anotado en `pagos`.

Al rechazar (`aprobado=False`), la factura queda en FRENAR firmado por el humano. **Nada se sobrescribe**: la resolución es una fila nueva con el mismo `factura_id`.

## 6. Autenticación que debe hacer la aplicación

El cerebro **no autentica**: valida identidades contra una lista. La app (Dev 3) tiene que:

1. **Autenticar en el servidor** a quien aprueba. Por ejemplo:
   - en Telegram, usar el `chat_id` que entrega la plataforma en el callback, nunca un texto que escriba el usuario;
   - en la web, una sesión o token.
2. Pasar a `reanudar` un **identificador estable** que coincida con `CEREBRO_APROBADORES`, por ejemplo `tg:123456789`.
3. Usar el `callback_query.id` de Telegram como `clave_idempotencia`. Así un reintento devuelve la misma resolución y nunca paga dos veces.
4. **No permitir que `/soyaprobador` agregue aprobadores por sí solo.** Exigir un código de un solo uso que conozca el operador, o editar `CEREBRO_APROBADORES` y reiniciar.
5. Mostrar Aprobar/Rechazar solo si `estado == "pendiente_humano"`. El cerebro igual rechaza cualquier otro caso.

## 7. Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `DB_PATH` | `blinka.db` | SQLite con `pagos`, `decision_log`, `reglas_versiones` y `eventos` (`*.db` está en `.gitignore`) |
| `REF_DATE` | `2026-10-17` | Fecha de referencia del mes, independiente del reloj. Un valor inválido es un error |
| `SIGNING_KEY_PATH` | Sin firma | Clave Ed25519 en PEM. Si no existe se crea con permisos 600. **Nunca al repo** (`*.pem` está ignorado) |
| `CEREBRO_APROBADORES` | — | Lista separada por comas, por ejemplo `tg:111,tg:222`. Si falta se usa `TELEGRAM_APROBADORES`; si faltan ambas, **no se aprueba nada** (solo se rechaza) |
| `TELEGRAM_APROBADORES` | — | Respaldo de la anterior |
| `CEREBRO_ADMINS` | — | Administradores que pueden ejecutar `reiniciar_demo` (lista separada por comas). Si falta, nadie puede reiniciar |
| `DB_BASE_PATH` | `<DB_PATH>_base.db` | Base sintética controlada desde la que se restaura la demo (por ejemplo `blinka_base.db`) |
| `CEREBRO_SEMANTICA` | Vacío = determinista | `jev` activa `CapaJev` (Jev vía OpenRouter); `claude` activa `CapaClaude` (SIN VALIDAR). Sin credencial, la capa queda no disponible y todo escala |
| `OPENROUTER_API_KEY` | — | Clave de OpenRouter para Jev. Solo viaja en la cabecera `Authorization`, por HTTPS a `openrouter.ai`, sin seguir redirecciones; se redacta de los errores y **nunca** se registra |
| `OPENROUTER_MODEL` | `typesafe/jev-1.13` | Solo se acepta la versión fijada. Cualquier otro valor (`jev-1.14`, `~typesafe/jev-latest`) deja la capa no disponible |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api` | Solo `https://openrouter.ai`. Se normaliza a `/api/alpha/decisions`; cualquier otro host deja la capa no disponible |
| `CEREBRO_SEMANTICA_MODELO` | `claude-opus-5-5` | Modelo de `CapaClaude` |
| `CEREBRO_TIMEOUT_AGENTE_S` | `3` | Timeout por agente y por consulta semántica |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | — | Solo si `CEREBRO_SEMANTICA=claude` |
| `DEMO_CACHE` | — | De Dev 1. `medir --modo live` exige que esté apagado |
| `OPENAI_MODEL` | `gpt-6-luna` | De Dev 1. Forma el nombre del extractor A en la clave de `cache/` |

El cerebro **no carga `.env`**: la app debe hacerlo (`python-dotenv`) antes del primer `decidir`.

## 8. Ejemplo de integración de extremo a extremo

```python
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile

load_dotenv()
from extraccion import extraer          # Dev 1
import cerebro                          # Dev 2

app = FastAPI()

@app.post("/ingest")
async def ingest(archivo: UploadFile, canal: str):
    # Guardar SOLO dentro de entrada/, con nombre propio (nunca la ruta del cliente),
    # y limitar tipo y tamaño (máx. 20 MB, como la ingesta de Dev 1).
    destino = Path("entrada") / f"{uuid4().hex}{Path(archivo.filename or '').suffix[:5]}"
    ...
    factura = extraer(destino, canal)           # nunca lanza
    decision = await cerebro.decidir_async(factura)   # nunca lanza
    return decision.model_dump(mode="json")

@app.post("/aprobar/{factura_id}")
def aprobar(factura_id: str, aprobado: bool, usuario_autenticado: str, callback_id: str | None = None):
    try:
        return cerebro.reanudar(factura_id, aprobado, usuario_autenticado,
                                clave_idempotencia=callback_id).model_dump(mode="json")
    except LookupError: raise HTTPException(404)
    except PermissionError: raise HTTPException(403)
    except cerebro.CadenaAlterada: raise HTTPException(423, "registro alterado")
    except cerebro.ReevaluacionNecesaria as e: raise HTTPException(503, str(e))
    except ValueError as e: raise HTTPException(409, str(e))

@app.get("/verificar")
def verificar():
    ok, fila = cerebro.verificar_cadena()
    return {"ok": ok, "fila_rota": fila}

@app.get("/evidencia/{factura_id}")
def evidencia(factura_id: str):
    return cerebro.paquete_evidencia(factura_id)

@app.post("/sandbox/{factura_id}")
def sandbox(factura_id: str, cambios: dict):
    return cerebro.simular_politica(factura_id, cambios)
```

`tests/test_contrato_cerebro.py::test_ejemplo_de_integracion_end_to_end` ejecuta este mismo flujo (`extraer` desde `cache/` → `decidir` → `reanudar` con lista y clave → `verificar_cadena` → evidencia → sandbox) sin red.

## 9. Policy Sandbox y evidencia del veto

```python
cerebro.simular_politica(factura_id, {"limite_pago_usd": 8000})
# {"modo": "SANDBOX", "advertencia": "Simulación de solo lectura: no se ejecutó ningún pago …",
#  "original": {"decision": "ESCALAR", …}, "simulada": {"decision": "PAGAR", …},
#  "reglas_que_cambiaron": [{"regla": "limite_pago", "antes": "falla", "despues": "cumple"}],
#  "razon": "Con limite_pago_usd 5000 → 8000, la decisión pasa de ESCALAR a PAGAR: …"}
```

- **Límites que se pueden simular:** `limite_pago_usd`, `tope_duro_usd`, `limite_mensual_proveedor_usd`, `limite_mensual_global_usd`, `saldo_disponible_usd`, `tolerancia_contrato`, `tolerancia_fx`, `tolerancia_monto_duplicado`, `umbral_sospecha`, `ventana_duplicados_dias`.
- **Qué evalúa:** solo los detectores deterministas, sobre una conexión `PRAGMA query_only`.
- **Qué no cambia:** un veto de agente, como el texto oculto, no se desarma con límites.
- **Contra qué estado evalúa:** el estado **actual** de la base, no el del momento en que se decidió. Una factura ya pagada sale como duplicado exacto.

`paquete_evidencia(factura_id)["responsable"]` responde "¿quién vetó?". Devuelve `{"tipo": "regla" | "agente" | "fallo_tecnico" | "sin_evidencia" | "humano" | "reglas", "nombre": …, "severidad": …, "motivo": …}`.

## 10. Cómo decide (resumen técnico)

1. Se relee `reglas.yaml` (su versión es el SHA-256) y se toma una **instantánea de lectura** del contexto. Los montos van en `Decimal` y centavos. Saldo = USD 25.000 − pagos del mes (USD 8.600 al inicio del set).
2. Los **cinco agentes corren en paralelo** (asyncio), cada uno con su timeout y **sin transacción de escritura abierta**. Cuando hay capa semántica, esta corre aparte y solo puede sumar hallazgos.
3. En la **transacción final** (`BEGIN IMMEDIATE`, sin esperas externas):
   - se verifica que las reglas no cambiaron;
   - se verifica que `pagos` coincide con el histórico y con las decisiones PAGAR;
   - se recalculan saldo, límites y duplicados;
   - se agrega, se sella con hash (y firma) y, si es PAGAR, se anota el pago simulado.

Dos solicitudes concurrentes no pueden gastar el mismo saldo ni pagar dos veces la misma factura.
