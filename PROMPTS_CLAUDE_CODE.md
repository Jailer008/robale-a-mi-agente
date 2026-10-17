# Prompts secuenciales para Claude Code — Róbale a mi agente

**Actualizado:** 17-oct-2026. **Objetivo:** ejecutar el empalme, terminar el MVP funcional y prepararlo para la entrega del 18-oct-2026 sin pisar trabajo de los 3 integrantes.

## Preparación local (WSL2 / terminal Bash)

Clona solo si aún no tienes el repo; si ya lo tienes, entra en tu checkout actual. Antes de cambiar rama o descargar cambios, verifica trabajo sin guardar:

```bash
git clone https://github.com/Jailer008/robale-a-mi-agente.git
cd robale-a-mi-agente
git status --short
git remote -v
git fetch origin --prune
git branch -a
```

Copia a la raíz del checkout `CLAUDE.md`, `PROMPTS_CLAUDE_CODE.md` y la carpeta `docs/hackathon/` de este paquete, SIN sobrescribir cambios de compañeros. Crea tu propia rama solo si `git status` confirma que es seguro:

```bash
git switch -c chore/empalme-inicial
claude
```

Si ya trabajas en una rama asignada, no crees otra por obligación. Usa los prompts a continuación en orden; **cada bloque es un mensaje independiente**, no los pegues todos a la vez. Si Claude propone una operación destructiva, detente.

---

## PROMPT 0 — Empalme forense y plan de ejecución (SOLO LECTURA)

```text
Actúa como tech lead e integrador principal en una hackathon, con prioridades de seguridad, pruebas y entrega. Estás dentro del repo `Jailer008/robale-a-mi-agente` y hay TRES desarrolladores simultáneos. La entrega interna está fijada para el 18-oct-2026 y el Demo Day para 19–20-oct-2026. NO asumas que el estado remoto sigue igual que en el momento de escribir estas instrucciones.

FASE G0: DIAGNÓSTICO ESTRICTAMENTE READ-ONLY DE ARCHIVOS VERSIONADOS. No edites código, no hagas commit, merge, push, rebase, reset ni checkout destructivo. Puedes consultar remotos, diffs, ramas, PRs y leer archivos. Si necesitas ejecutar tests, primero muestra los comandos y aclara el impacto local (venv/cache); no uses claves ni APIs reales sin autorización.

1. Lee íntegros CLAUDE.md y los cuatro documentos en docs/hackathon/ (00_COMUN, DEV1, DEV2, DEV3). Si faltan, DETENTE e indica los nombres faltantes: no sustituyas esos contratos con suposiciones.
2. Revisa `git status`, remotos, rama actual, HEAD SHA, ramas remotas, PRs, commits recientes, diffs con main y archivos existentes. No confundas 'no está en main' con 'no está implementado': puede estar en PR o ramas.
3. Investiga especialmente PR #1 `feat/dev1-datos-extraccion` de Dev 1, y detecta si aparecieron ramas o PRs de Dev 2/Dev 3. Revisa contratos públicos: schemas.py, reglas.yaml, extraccion.extraer, decidir, reanudar, verificar_cadena, app API.
4. Construye matriz por componente: REQUERIDO | EN MAIN | EN RAMA/PR | VALIDADO CON TEST | PENDIENTE | RESPONSABLE. Incluye datos de 15 facturas, extracción A/B, escáner oculto, reglas, cinco agentes, histórico, hash/firma, métricas, Streamlit, FastAPI, Telegram, despliegue y video.
5. Identifica contradicciones entre documentos, PRs y código (en especial saldo mensual, campos monetarios y tasas, caches, fuentes FX, tiempos de espera y significado de 'PAGAR'). Distingue hechos observados vs declaraciones en PR sin reejecutar.
6. Haz un ranking de P0 / P1 / P2 teniendo en cuenta 0 PAGAR indebidos, el mínimo de integración E2E y el plazo. Especifica tareas que corren en paralelo sin solapamiento.
7. Entrega un plan de gates G1 a G6, comandos de validación y qué trabajo debes NO TOCAR porque pertenece a otro integrante.

FORMATO DE RESPUESTA: 1) estado del repo con SHA, 2) matriz, 3) riesgos críticos, 4) próximos 3 pasos ejecutables con responsable y criterio de aceptación, 5) preguntas de bloqueo SOLO si no puedes continuar con seguridad.
Detente al final de G0. No escribas código todavía.
```

## PROMPT 1 — Auditoría y fusión controlada del PR de Dev 1

```text
Continuemos con G1: verificar la rama/PR de Dev 1 `feat/dev1-datos-extraccion` (PR #1). IMPORTANTE: no modifiques su implementación sin permiso del autor; no hagas merge ni push automáticamente.

1. Comprueba que el árbol de trabajo local está limpio, realiza fetch de la rama remota y examina PR y diff vs main. Si main o la rama cambiaron, registra nuevos SHA.
2. Valida que `schemas.py` y `reglas.yaml` conservan el contrato común. Compara los 15 archivos originales, 15 JSON, ground_truth.csv, proveedores, contratos, histórico, FX y README de datos.
3. Si el entorno lo permite, ejecuta en WSL2 con Python 3.12: `uv sync`, `uv run pytest -q`, `uv run ruff check .`, `git diff --check` y escaneo de seguridad pertinente. Registra salida exacta. NO invoques `extraccion.medir` en modo LIVE hasta verificar disponibilidad y coste de APIs y recibir autorización; si lo pruebas con caché, indícalo inequívocamente.
4. Revisa las invariantes de extracción: nunca excepción al exterior, hash del ORIGINAL, A/B independientes o degradación marcada, timeout, aritmética, archivo corrupto, PDF con instrucciones ocultas, imagen borrosa, entrada .eml, canales y ausencia de credenciales.
5. Identifica diferencias entre lo que indica la descripción del PR y lo que realmente está versionado. Revisa en particular el `cache/` que figura en el historial aunque `.gitignore` lo ignore; verifica si es estrictamente sintético y si requiere un `demo/fixtures/` controlado. Nunca lo muestres como inferencia en vivo.
6. Verifica que el contexto permite a Dev 2 reproducir las 15 decisiones, incluida la factura 13 por saldo mensual y la 12 por límite por pago. No cambies `reglas.yaml` para maquillar los tests.
7. Si faltan pruebas CI, propón workflow mínimo `uv sync --locked`, pytest y ruff; solo implementar en una rama propia y bajo revisión del equipo.

Entrega un INFORME DE REVISIÓN con PASS/FAIL/SKIP por chequeo, fallos priorizados, cambios sugeridos para Dev 1 y decisión MERGE-READY / CONDITIONAL / BLOCKED. Si está CONDITIONAL, especifica el fix mínimo. No hagas merge: enlista comandos exactos que el integrador autorizado ejecutaría después de aprobarlo, y cómo verificar main tras fusionar.
```

## PROMPT 2 — Dev 2: núcleo determinista y pruebas adversariales (código)

```text
G2. Solo ejecuta implementación si soy Dev 2 o el responsable autorizado del módulo `/cerebro`. Estás construyendo sobre el commit validado de Dev 1; primero verifica que los datos y `schemas.py` están presentes. No crees fixtures duplicadas, no cambies contratos comunes sin aprobación, no edites /datos, /extraccion ni /app. Trabaja en rama feat/dev2-cerebro-decision (o rama propia existente).

OBJETIVO PRIMERO: que `from cerebro import decidir, reanudar, verificar_cadena` funcione con los JSON de `datos/facturas_json` sin llamadas de red y sin pagos indebidos.

TDD. Primero crea tests que fallan para la matriz exacta:
01–06 PAGAR; 07 FRENAR; 08 ESCALAR; 09 ESCALAR; 10 ESCALAR; 11 ESCALAR; 12 ESCALAR; 13 FRENAR; 14 FRENAR; 15 ESCALAR. Añade tests de errores técnicos, datos vacíos, prompt injection en texto_libre, veto monotónico, idempotencia, duplicados, saldo, límites mensuales y aprobación humana indebida.

Implementa por etapas mínimas en `cerebro/`:
- Contexto y almacenamiento SQLite con histórico precargado de modo idempotente, pagos, decisiones, versiones de reglas y eventos; evita double-counting. `version_reglas = SHA-256(reglas.yaml)`. Para los fixtures usa fecha de referencia 2026-10-17, sin depender del reloj real.
- Aritmética determinista con Decimal y centavos enteros, tasas ficticias `unidades_por_usd`; saldo disponible = 25000 menos pagos históricos del mes menos pagos nuevos confirmados. Distingue presupuesto mensual de saldo. Explicaciones y tasa/fecha/fuente guardadas.
- Reglas `evaluar(ctx) -> (ALLOW|DENY, reglas_fallidas)` con severidad. Si Cedar resulta incierto o difícil de integrar, usa Python puro según el plan, documentando el recorte. Proveedor bloqueado, saldo insuficiente, duplicado exacto, tope duro y texto oculto se frenan; excepciones solo escalan.
- `decidir(factura) -> Decision`: por ahora puede llamar a agentes locales básicos (o stubs explícitos) pero nunca depende de llamadas externas. Los agentes entregan Hallazgo, NUNCA devuelven PAGAR. `sev=max(sev_reglas, sev_hallazgos, sev_fallos)` y PAGAR solamente con extraccion_ok, ALLOW, sin hallazgos ni errores.
- `reanudar(factura_id, aprobado, aprobador)`: solo pendientes, aprobador autorizado, transición idempotente y atómica. Una FRENAR no se aprueba, incluyendo tope duro/bloqueos; reevaluar controles duros antes de materializar un pago simulado. No transferir dinero real.

Mantén el esquema público de Decision. Prohibido cambiar severidades para obtener resultados verdes. Tras cada subpaso ejecuta tests; muestra evidencia real. Si te topas con un desacuerdo entre ground_truth y un control crítico, muestra caso, causa y propuesta; NO ajustes fixture/rules silenciosamente.

Entrega archivos, diff, tests FAIL→PASS, estado de 15 casos y lista de pendientes para G3. No hagas merge sin revisión.
```

## PROMPT 3 — Dev 2: comité de 5 agentes, auditoría, medición

```text
G3. Continúa sobre el G2 validado dentro de /cerebro. No cambies trabajo de Dev 1/3 ni los esquemas compartidos. Implementa el sistema completo respetando `DEV2_cerebro_decision.md`, priorizando resultados reproducibles y seguridad sobre sofisticación.

1. Agentes concurrentes (5): duplicados (exacto Python=FRENAR, difuso si existe evidencia -> ESCALAR); contrato (matching de líneas frente a contrato, fuera de 5% o ítem ausente -> ESCALAR; fan-out por línea hasta 8); beneficiario/cuenta (cuenta distinta ESCALAR, proveedor bloqueado FRENAR); seguridad (texto_oculto o instrucciones dirigidas al sistema FRENAR); presupuesto/FX (saldo, límites y desviación FX). Cada agente devuelve `list[Hallazgo]` y emite evento por factura.
2. No uses LLMs para dinero, fechas, límites o sumar. Emplea Jev versión fijada SOLO si está documentado, instalable, comprobable y existen claves; alternativa de salida estructurada permitida por el plan. Timeout en cada verificación semántica de 3 segundos; fallo o ausencia de credencial -> al menos ESCALAR. Para casos inequívocos usa código. Prohíbe cualquier decisión PAGAR de los modelos.
3. Orquestación concurrente con fan-in y veto monotónico; puede usar asyncio si LangGraph amenaza el plazo. Proteger de race conditions en SQLite, registro duplicado y ejecuciones concurrentes. Resultado incluye explicación clara en español y contrafactual solo sustentado por reglas reales; no inventar motivo ni causalidad.
4. Auditoría encadenada: canonical JSON estable, hash_prev y hash SHA-256, verificación detecta primera fila alterada, datos de políticas/FX, timestamps; Ed25519 si hay tiempo y clave separada. Probar edición maliciosa, borrado, reordenamiento y reintentos. No afirmar que es a prueba de alteración si solo es hash sin almacenamiento o firma externa.
5. `python -m cerebro.medir`: corre 15 casos con fixtures en entorno aislado y restaurable, compara contra ground_truth, guarda resultados.json con matriz de confusión 3x3, pagos indebidos, autonomía definida explícitamente (% de decisiones finales correctas sin humano), latencia y costo solo medidos. No confundir cache/mock con LIVE. No mutar el histórico permanentemente al medir, ni contar una aprobación dos veces.
6. Pruebas adicionales: severidad nunca decrece (property tests o barrido exhaustivo), un fallo de agente no bloquea la aplicación pero ESCALA, 14 frena por texto oculto aun si extracción tiene éxito, 15 escala por lectura dudosa, 13 frena por saldo y 12 escala por importe según fixtures.

Criterio de aceptación: tests y medición reproducibles, CERO falsos PAGAR entre 15 fixtures, 5 eventos por factura o eventos explícitos de fallo, `decidir`, `reanudar`, `verificar_cadena` públicos. Reporta comandos y evidencias. Si no puedes completar un punto, indica P0/P1/P2 y nunca simules resultado exitoso.
```

## PROMPT 4 — Dev 3: producto usable y demo extremo a extremo

```text
G4. Ejecutar SOLO desde la rama autorizada del Dev 3 (o por el Dev 3). Lee DEV3 y contrato común. Tu propiedad es /app, más README/despliegue tras revisión conjunta. No edites /cerebro, /extraccion, datos, schemas.py o reglas.yaml. Trabaja desde mocks hasta que las APIs reales estén integradas.

1. Construye la UI Streamlit legible por videollamada: Reglas (al menos lectura), Bandeja, Documento, Comité en vivo con 5 agentes (pantalla estrella), Métricas. Incluye 3 estados PAGAR/ESCALAR/FRENAR, detalle A/B, texto oculto, hallazgos, contrafactual, explicación y verificador hash. Diseña responsive, sin sacrificar estabilidad.
2. Implementa API FastAPI según contratos: POST /ingest (archivo, canal), POST /aprobar/{factura_id}, GET /decisiones, GET /eventos/{factura_id}, GET /verificar, POST /paquete-jurado. Examina contradicción entre "POST /ingest devuelve Decision" y BackgroundTasks: preserva una respuesta/documentación coherente; si eliges asincronía, define identificador/status y adapta cliente sin romper contratos existentes.
3. Integra `extraer`→`decidir` con archivos subidos; respuesta de error honesta y fail-closed. No presentar en bandeja un pago como transferido cuando solo fue clasificado/autorizado (usar "autorizado (simulado)"). Maneja reinicio, refresh y estados pendientes sin duplicar decisiones.
4. Seguridad del endpoint de aprobaciones: autenticación/autorización del servidor, listado de aprobadores (IDs verificados), anti-replay e idempotencia; no permitir que cualquier usuario se autoeleve a aprobador con `/soyaprobador` ni aceptar 'aprobador' inventado en un body sin validarlo. Respetar FRENAR irreversible. Validar canales, tamaño MIME, rutas y nombres de archivos; sin secretos en logs o repo.
5. Telegram (polling, si hay credencial): recibe imágenes/PDF/texto; notifica motivo/estado. Botones inline aprobar/rechazar sólo para whitelist. Si no está disponible, UI + botón paquete-jurado simulan flujo de prueba de forma explícita. Jamás solicitar credenciales en chat público.
6. Diseño de demo: paquete de las seis trampas 07,08,10,11,12,14, un contador real derivado de resultados medidos (sin hardcodear '0'), modo LIVE vs CACHÉ vs MOCK claramente visible, QR seguro, plan B de video 90s y capturas. La caché de demo debe corresponder a hashes de documentos y no estar etiquetada como llamada nueva al modelo.
7. Arranque local fiable documentado. Docker/despliegue sólo después de demo local E2E estable; no introducir cambios riesgosos a última hora.

Entregables: endpoints documentados + tests con clientes falsos, cinco pantallas funcionando, flujo de una limpia/una ESCALAR/una FRENAR, estado de bot real vs simulado, comando único de arranque y captura/evidencia. Commits pequeños en tu rama, PR a main para revisión.
```

## PROMPT 5 — Integración final y pruebas de seguridad

```text
G5. Ahora actúas como integrador AUTORIZADO en una rama de integración nueva desde main actual, después de aprobar los PRs de Dev 1, Dev 2 y Dev 3. Antes de modificar cualquier cosa: verifica SHA de main, estado de cada PR y suite de cada módulo. NO fusiones ni reescribas trabajo ajeno sin consentimiento de los autores.

META: pipeline REAL dentro del entorno de test `archivo->extraer->decidir->UI/API`, más aprobación segura y registro auditable. Toda la evidencia debe ser verificable y reproducible desde checkout limpio.

Prueba de forma aislada (base SQLite temporal/fija, caché conocida, credenciales opcionales) los 15 documentos contra ground_truth. Calcula falsos PAGAR y falso FRENAR/ESCALAR; explica autonomía vs seguridad. Ejecuta simultáneamente casos nuevos: PDF malicioso con instrucciones, cuenta alterada, proveedor bloqueado, duplicado exacto y disfrazado, saldo insuficiente, sobre tope duro, solicitud de aprobación no autorizada, doble callback Telegram, misma factura enviada dos veces, error/timeout de modelo, cache corrupta, contenido inesperado y manipulación de decision_log.

No permitir que
- una falla cambie FRENAR a ESCALAR o PAGAR;
- un aprobador humano materialice FRENAR o salte controles duros;
- una factura de prueba se contabilice en dos pagos o manipule el saldo entre corridas;
- una simulación aparezca como pago bancario real;
- el modo demo altere la política sin indicarlo.

Métricas que exijo: número de tests PASS/FAIL/SKIP, las 15 decisiones frente a esperado, pagos indebidos (debe ser 0 para aprobar), autonomía calculada sobre decisiones finales correctas sin humano, latencia promedio, costo de llamadas LIVE verificadas solamente, hash chain OK/FAIL, cobertura de endpoints y modo de ejecución LIVE/CACHÉ/MOCK.

Identifica P0 que bloquearían Demo Day; reduce funcionalidad secundaria antes que reducir seguridad. Genera `docs/INFORME_INTEGRACION.md` con tabla de evidencia y comandos. Solo cuando esté aprobado, crea PR y ofrece comandos de merge/tag `v1-demo`; no hagas push, merge o tag sin que yo lo autorice.
```

## PROMPT 6 — Congelación, entregables y pitch

```text
G6. Tenemos entrega el 18-oct-2026 y Demo Day el 19–20-oct-2026. Revisa el gate G5: si hay fallos P0, prioriza corregirlos; si no hay fallos P0, CONGELA FEATURES y trabaja sólo en fiabilidad/presentación. No implementes componentes nuevos por estética.

1. README listo para jurado: propuesta de valor, 3 principios, arquitectura Mermaid, contratos, prerequisitos Python3.12/uv, configuración de variables sin claves, comandos para correr API/UI/bot, data set sintético, pruebas, métricas verdaderamente medidas y limitaciones.
2. Checklist de entrega y Demo Day: repo público, rama main verificada, video respaldo 90s, capturas, QR, comando de arranque, credenciales verificadas sin exponerlas, restauración de BD, plan B local/caché, paquete seis facturas listo, una persona habla, una opera, una supervisa el bot, y tres ensayos cronometrados.
3. Pitch de 3 min: 0:00 amenaza y QR, 0:20 demo de trampas y comité, 1:30 reglas y contrafactual, 2:10 métricas reales, 2:40 auditoría/hash y cierre. Si un dato de contexto del guion original no tiene fuente verificada, quítalo o busca una fuente apropiada; no inventes estadísticas ni ahorros.
4. Incluye fallbacks explícitos: caída Telegram -> paquete-jurado web; API de extracción -> caché rotulada; caída total -> video grabado, nunca afirmar 'LIVE' si está cacheado.
5. Devuelve un GO/NO-GO sustentado en evidencia, 5 riesgos remanentes y el guion listo para ensayar. No modifiques contratos ni datos de prueba para maquillar métricas.
```

## Priorización de última hora

**P0 (no recortar):** 15 ground truths, parser fail-closed, reglas puras, cinco hallazgos/agentes o fallback explícito, cero falsos PAGAR, impedir aprobación de FRENAR, UI de comité, métricas reales, plan B video, hashes/verificador mínimo.

**P1 (si quedan recursos):** extracción con dos proveedores en vivo, Telegram real autenticado, CI, firma Ed25519, despliegue cloud estable.

**P2 (se recorta primero):** panel editable de reglas, LangGraph si complica, Jev si no está disponible, Cedar si bloquea, Docling, integraciones externas y estética no funcional.

El objetivo no es marcar todo como terminado, sino demostrar un sistema creíble, seguro y reproducible sin inventar pruebas ni pagos.
