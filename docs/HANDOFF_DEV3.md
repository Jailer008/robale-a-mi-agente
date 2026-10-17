# Róbale a mi agente — Entrega de Dev 2 a Dev 3

**Hackathon 30X · Reto Blinka**  
**Fecha de traspaso:** 17 de octubre de 2026  
**Entrega prevista:** 18 de octubre de 2026 · **Demo Day:** 19–20 de octubre  
**Repositorio:** https://github.com/Jailer008/robale-a-mi-agente  
**Responsable entrante:** Dev 3 (experiencia, API, demo y despliegue)

> **Importante:** Este documento es un inventario de traspaso, **no** una certificación de que G5 o el despliegue estén terminados. Claude Code se quedó sin créditos durante G5. El estado exacto de los archivos de G5, los commits y las pruebas debe inspeccionarse en la máquina de Dev 2 antes de afirmar funcionalidades completadas.

## 1. Estado conocido y evidencias

| Entrega | Estado / evidencia previa | Observación |
|---|---|---|
| Dev 1 — datos y extracción | PR #1 abierto, 220 tests reportados y verificados en G1 | Fusionar/revisar por alguien con permiso de escritura; no se debe duplicar trabajo |
| Dev 2 — G2/G3 | Código local en `feat/dev2-cerebro`; 496 tests reportados en G3 | Reglas, cinco dominios, firma, métricas, reanudar, auditoría y sandbox |
| Dev 2 — Jev / OpenRouter | 553 tests reportados, integración HTTP con dobles simulados | **Prueba LIVE aún no confirmada**; jamás presentar como validada en vivo |
| Dev 2 — G4 seguridad v2 | **619 tests reportados, 15/15 casos v2, 0 falsos PAGAR** en el set MOCK/CACHÉ | Último HEAD reportado `40bebdf`. No se ha verificado aquí estado posterior |
| G5 — Attack Lab anticipado por Dev 2 | **EN CURSO / NO AUDITADO** | Revisar worktree(s), archivos, commits y pruebas actuales |
| API, UI, bot, Railway, URL pública | **No comprobado** | No anunciar despliegue o demo móvil terminada sin pruebas reales |

**Estado remoto consultado al hacer el empalme:** `main`, `feat/dev1-datos-extraccion` y `feat/dev1-v2-falsificacion` estaban presentes; PR #1 seguía abierto. **No aparecía la rama Dev 2 ni la de Attack Lab**. Volver a consultar antes de fusionar.

## 2. Invariantes que jamás deben romperse

- El producto **no mueve dinero**: PAGAR significa autorización **simulada**.
- **Veto monotónico:** 0 PAGAR, 1 ESCALAR, 2 FRENAR; el resultado final usa severidad máxima. Ningún LLM o Jev autoriza PAGAR.
- **Fail-closed:** error, timeout, extracción incompleta, FX desconocido, desacuerdo o semántica no disponible → nunca aprobar automáticamente.
- **G4:** cuenta no registrada o proveedor no permitido → **FRENAR no aprobable**, incluso frente a un aprobador humano.
- Extracción incierta → ESCALAR **no aprobable** hasta reevaluación fiable.
- Un cliente móvil nunca decide `aprobable`, `extraccion_ok`, `id_documento`, `codigo_principal` ni la severidad; el servidor calcula todo.
- La UI **muestra `decision.decision`**, no `cedar` como si fuera el resultado agregado.
- Cuentas enmascaradas y secretos fuera del repositorio, las respuestas públicas y los logs.

## 3. Contrato público de Dev 2 (verificar firmas exactas en código)

Documentación primaria: `cerebro/README.md`, especialmente secciones 5, 6, 11 y 12; `schemas.py`; `docs/hackathon/00_COMUN.md`; `DEV3_experiencia_demo.md`; aviso `AVISO_DEV2_cambios.md` (posiblemente aún en Descargas del compañero).

Funciones reportadas: `decidir_async`, `decidir`, `reanudar`, `reevaluar`, `verificar_cadena`, `paquete_evidencia`, `vista_publica` y `reiniciar_demo`. **Comprobar argumentos, retornos y excepciones actuales; no deducir firmas a partir de nombres.**

Campos G4 añadidos a Decision/Hallazgo:

```python
# Hallazgo
codigo: str = ""

# Decision
codigo_principal: str = "OK"
aprobable: bool = False
accion_requerida: str | None = None
```

Errores comunicados: `NoAprobable` (409), `ReevaluacionNecesaria` (503), `ReinicioOcupado` (409), además de errores de autorización e integridad. Autenticar servidor-side y mapear excepciones sin filtrar datos internos.

## 4. Matriz obligatoria de demo G4 (ground truth v2)

| Casos | Resultado esperado | Código principal / protección |
|---|---|---|
| 01–06 | PAGAR | `OK` · autorización simulada |
| 07 | FRENAR | `DUPLICADO_EXACTO` · no aprobable |
| 08 | ESCALAR | `DUPLICADO_DIFUSO` · aprobable solo tras revalidación |
| 09 | FRENAR | `PROVEEDOR_NO_PERMITIDO` · no aprobable |
| 10 | FRENAR | `CUENTA_NO_REGISTRADA` · no aprobable |
| 11 | ESCALAR | `CONTRATO` · revisión humana bajo reglas |
| 12 | ESCALAR | `LIMITE_PAGO` · aprobación controlada |
| 13 | FRENAR | `SALDO` · no aprobable |
| 14 | FRENAR | `TEXTO_OCULTO` · no aprobable |
| 15 | ESCALAR | `EXTRACCION` · **no aprobable** sin reevaluar |

**Atención:** el archivo `datos/ground_truth.csv` de Dev 1 podía seguir en v1 (09 y 10 = ESCALAR). El cerebro G4 tiene sus expectativas v2. Coordinar la modificación con Dev 1 y **no cambiar fixtures a escondidas**.

## 5. Qué debe inspeccionar primero Dev 3: G5 sin terminar

Desde la carpeta del repositorio de Dev 2:

```powershell
git worktree list
git branch -avv
git status --short
git log -5 --oneline --decorate
```

Abrir **la carpeta del worktree donde Claude implementó G5** (si existe) y ejecutar de nuevo `git status --short` y `git log -5 --oneline`. Puede llamarse `feat/attack-lab-dev2-handoff` o tener otro nombre; **no asumirlo ni eliminar worktrees**. Guardar/commitear primero archivos nuevos o sin seguimiento antes de cambiar ramas. Comparar qué existe realmente en `app/`, `tests/`, Dockerfiles y `docs/` con este inventario. Si hay código parcial, conservarlo y cerrar un MVP antes de rediseñar.

Especificación original de G5: `paquete_attack_lab/01_G5_CONSTRUIR_ATTACK_LAB.md` (si se copió al repositorio; de lo contrario solicitar el paquete original a Dev 2).

## 6. Pendientes clasificados para Dev 3

### P0 — Obligatorios para una demo real

- [ ] Recuperar todo G5: ramas, archivos nuevos/no commiteados, commits, pruebas y diferencias con G4.
- [ ] Verificar que `app/api.py` y `app/servicios.py` existan y **consuman el cerebro real**, sin retornar decisiones pregrabadas como reales.
- [ ] Construir/probar `POST /simular`: formularios sintéticos editables, validación **servidor-side**, nuevo hash por factura manipulada y `decidir_async` genuino. Etiquetar **DATOS SINTÉTICOS — EVALUACIÓN REAL**.
- [ ] Implementar pantalla de jurado móvil con seis presets: limpia, cuenta cambiada, proveedor desconocido, monto alto, duplicado, inyección; resultados con `codigo_principal`, `aprobable` y `accion_requerida`.
- [ ] Poner **bloqueo server-side** de aprobación de facturas FRENAR o ESCALAR no aprobables; exigir aprobador autenticado para rutas administrativas.
- [ ] Bandeja, comité (cinco agentes, solo eventos verdaderos), documento/evidencia y métricas; distinguir MOCK/CACHÉ/LIVE.
- [ ] Ejecutar prueba de regresión: `uv sync --locked`, `uv run pytest -q`, `uv run ruff check .`, `git diff --check`; reportar **resultados actuales**, no repetir 619 si han cambiado.
- [ ] Test adversarial API: cuenta atacante → FRENAR, proveedor falso → FRENAR, duplicado → FRENAR, inyección → FRENAR, > límite normal → ESCALAR, extracción dudosa → ESCALAR no aprobable, llamadas de aprobación prohibidas → 403/409 según contrato.
- [ ] Integrar rama/PR a repositorio compartido con permisos reales, **sin reescribir commits del equipo**.
- [ ] Preparar y comprobar despliegue Railway con URL pública HTTPS; probarlo **desde un celular real**. Si no hay tiempo, presentar demo local más video reproducible.

### P1 — Demostración de calidad y seguridad

- [ ] Subida PDF/JPG/PNG/EML/TXT a `extraccion.extraer` con tamaños, extensiones, MIME y almacenamiento seguros; sin afirmar LIVE si solo hubo caché.
- [ ] Evidencia del veto y Policy Sandbox de solo lectura (ambos reportados en Dev 2).
- [ ] Aprobación humana real por rol (UI/Telegram si hay tiempo): lista de aprobadores, idempotencia, doble clic, estado, revisión del presupuesto.
- [ ] Botón «Paquete del jurado», reset de demo restringido al administrador y estado SQLite reproducible.
- [ ] `README.md`, guía de despliegue, guion 3 min, video de respaldo 90 s y capturas reales.

### P2 — Opcionales si P0 y P1 están verificados

- [ ] Animación de eventos sin inventar latencias ni probabilidades.
- [ ] Mejoras visuales, QR y dominio personalizado.
- [ ] Jev LIVE luego de probar conectividad, configurar límites de gasto y contrastar autonomía; no bloquear demo por ello.
- [ ] Observabilidad adicional como Langfuse.

## 7. Railway — objetivo de despliegue y límites

Se recomiendan **dos servicios** en Railway: **API FastAPI** (único dueño de SQLite y de la firma) y **UI Streamlit** (HTTP contra API). Configurar un volumen persistente solo en API y **una réplica/un worker de escritura** para SQLite. Enlace público solo para UI, y API con controles de autorización/consumo si se expone. No usar dos servicios escribiendo el mismo SQLite.

Ejemplo de variables del servicio API (valores en panel Railway, nunca en Git):

```dotenv
DB_PATH=/data/blinka_demo.db
SIGNING_KEY_PATH=/data/firma_ed25519.pem
REF_DATE=2026-10-17
DEMO_CACHE=1
CEREBRO_SEMANTICA=
# Configurar otras claves/autorizaciones como variables privadas según el código real
```

`CEREBRO_SEMANTICA=jev` solo después de confirmar proveedor, costos, timeout y resultados LIVE; en demo inicial preferir determinista o mocks **etiquetados**. Montaje de volumen `/data`; no regenerar la clave privada Ed25519 tras cada reinicio. Verificar bind `0.0.0.0:$PORT`, healthcheck y persistencia tras redeploy. El desarrollo en Railway y sus posibles costos requieren autorización de la cuenta correspondiente.

**No hay evidencia confirmada todavía de URL de despliegue, Docker funcional o test móvil superado.**

Especificación original de G6: `paquete_attack_lab/02_G6_DESPLEGAR_RAILWAY.md`.

## 8. Coordinación y propiedad

- **Dev 1:** `datos/`, `extraccion/`, fixtures v2 y ajustes del extractor.
- **Dev 2:** `cerebro/`, reglas v2, firma, medición y contratos; desarrolló un *adelanto* de `app/` en G5 que necesita revisión.
- **Dev 3 (recibe):** `app/`, API, UI, integración móvil, bot, Railway, ensayos, demo y presentación. Revisar y mejorar G5 sin reconstruir lo que funcione.
- **Integración:** resolver PR #1, rama Dev 1 de falsificación y publicación de Dev 2; validar contratos y pruebas después de cada merge. No ejecutar merges cruzados sin autorización del propietario.

## 9. Criterios de aceptación para declarar «listo»

1. PR e historial del equipo preservados, sin secrets ni cambios sin guardar perdidos.
2. Tests actuales todos verdes y reporte real de comandos; auditoría de permisos y validación adversarial.
3. Seis escenarios desde navegador móvil al backend real, con resultados según matriz v2; **0 falsos PAGAR en los casos medidos**.
4. Ningún usuario sin autorización puede aprobar un FRENAR, cambiar reglas reales, resetear base o leer evidencia sensible.
5. Decisiones registradas y cadena de integridad verificable; reinicio y persistencia comprobados.
6. URL pública real, smoke test externo, video de respaldo, instrucciones reproducibles.
7. Métricas separadas por MOCK/CACHÉ/LIVE; **no afirmar fraude real detectado, ejecución bancaria ni seguridad absoluta**.

## 10. Datos que Dev 2 debe pegar aquí antes de pasar el enlace al compañero

**Worktree G5 (ruta local):** PENDIENTE DE INSPECCIÓN  
**Rama y SHA actual:** PENDIENTE DE INSPECCIÓN  
**Commits G5 hechos:** PENDIENTE DE INSPECCIÓN  
**Archivos G5 nuevos/modificados:** PENDIENTE DE INSPECCIÓN  
**Pruebas realizadas desde que inició G5:** PENDIENTE DE EJECUCIÓN  
**Estado de Railway y URL:** NO CONFIRMADO  
**Bloqueo de permisos GitHub:** según última revisión, cuenta conectada sin push al repo principal  
**Contacto para dudas de contrato:** Dev 2, con `cerebro/README.md` como referencia canónica.

---

**Mensaje de entrega:** «Comparto el cerebro G4 ya validado y el trabajo parcial del Attack Lab (G5). Todo está en la rama indicada en esta entrega. Por favor, primero audita la implementación y conserva los commits existentes. Tu prioridad es terminar el flujo desde celular, probar los seis escenarios contra el cerebro real, desplegar en Railway y cerrar el video/pitch. No marques nada como LISTO sin evidencia».
