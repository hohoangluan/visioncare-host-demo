FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libsndfile/espeak-ng: thư viện âm thanh + phonemizer mà TTS (vieneu) cần.
# curl: healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 espeak-ng curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Trọng số model (models/stt, models/intent_encoder, models/.cache) không nằm
# trong image: docker-compose mount vào /app/models.
RUN useradd --system --uid 1000 --create-home app \
    && mkdir -p /app/storage /app/models \
    && chown -R app:app /app/storage /app/models
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
