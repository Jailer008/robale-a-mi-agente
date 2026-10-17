# Attack Lab · UI Streamlit. SOLO desarrollo local. No abre la base ni la firma: habla con la API.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/srv/.venv
RUN pip install --no-cache-dir uv==0.11.13
WORKDIR /srv

COPY app/ui/pyproject.toml app/ui/uv.lock ./
RUN uv sync --locked --no-dev

COPY app/ui/ui.py app/ui/paginas.py app/ui/estilo.py app/ui/cliente.py ./

RUN useradd --system --uid 10002 attacklabui
USER attacklabui
ENV API_URL=http://api:8000
EXPOSE 8501
CMD ["/srv/.venv/bin/streamlit", "run", "ui.py", "--server.address", "0.0.0.0", "--server.port", "8501", \
     "--server.headless", "true", "--browser.gatherUsageStats", "false"]
