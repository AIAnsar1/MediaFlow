# syntax=docker/dockerfile:1

FROM python:3.12-slim as builder

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

# Установка uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Копируем файлы зависимостей
COPY pyproject.toml uv.lock ./

# Устанавливаем зависимости
RUN uv sync --frozen --no-dev

# Production image
FROM python:3.12-slim

WORKDIR /app

# Runtime зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

# Копируем uv и venv
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app/.venv /app/.venv

# Копируем код
COPY app/ ./app/
COPY bot/ ./bot/
COPY database/ ./database/
COPY i18n/ ./i18n/
COPY models/ ./models/
COPY repositories/ ./repositories/
COPY resources/ ./resources/
COPY schemas/ ./schemas/
COPY services/ ./services/
COPY workers/ ./workers/
COPY main.py alembic.ini ./

# Создаём директории
RUN mkdir -p storage/logs storage/temp

# Переменные окружения
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "main.py"]
