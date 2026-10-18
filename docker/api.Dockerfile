# Attack Lab · API (FastAPI + cerebro + extracción). SOLO desarrollo local; no es un despliegue.
# Un único proceso y worker: es el único que abre DB_PATH y la clave de firma.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/srv/.venv
# WeasyPrint (dibujo de las facturas falsificadas) necesita Pango, HarfBuzz-Subset y una fuente con
# glifos en español: sin ellos la API no arranca (extraccion.render se importa al iniciar).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
       fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.13
WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY schemas.py reglas.yaml ./
COPY cerebro ./cerebro
COPY extraccion ./extraccion
COPY datos ./datos
COPY cache ./cache
COPY app/__init__.py app/api.py app/auditoria.py app/config.py app/documentos.py app/falsificar.py app/seguridad.py \
     app/servicios.py app/sintetico.py ./app/

RUN useradd --system --uid 10001 attacklab && mkdir -p /data && chown attacklab /data
USER attacklab

# Base, base controlada, clave de firma y archivos subidos viven en el volumen /data (nunca en la imagen).
ENV DB_PATH=/data/blinka_demo.db DB_BASE_PATH=/data/blinka_base.db SIGNING_KEY_PATH=/data/firma_ed25519.pem \
    APP_ENTRADA_DIR=/data/entrada
EXPOSE 8000
CMD ["/srv/.venv/bin/uvicorn", "--factory", "app.api:crear_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
