# Imagem do serviço "bot" (seção 10.7 da spec). Build local, sem porta publicada —
# o WAHA fala com ele pela rede interna do compose.
FROM python:3.12-slim

# Binário oficial do uv, pinado na mesma versão usada em dev/CI (ver Makefile e ci.yml).
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Pango/fontes para o WeasyPrint gerar o PDF do /ranking (M62, ADR-0060).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Camada de dependências isolada do código: só reinstala se pyproject/uv.lock mudarem.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
