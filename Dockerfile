FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY static ./static

RUN pip install ".[bot]" \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/downloads \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Healthcheck compose file mein web service ke liye set hai — bot container
# (same image) HTTP serve nahi karta, isliye yahan hardcode nahi kiya.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
