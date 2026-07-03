FROM python:3.13-slim

# System dependencies:
#   libmagic1 — python-magic file-type detection from bytes
#   libreoffice-{writer,calc,impress} — headless office→PDF conversion (doc/docx, xls/xlsx, ppt/pptx)
#   fonts-liberation — sane default fonts so converted PDFs render correctly
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# uv — dependency manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Manifests first — so the dependency layer is cached between builds
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]