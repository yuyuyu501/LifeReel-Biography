FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

WORKDIR /opt/deps
COPY apps/api/pyproject.toml apps/api/README.md ./
RUN mkdir -p src/lifereel_api \
    && touch src/lifereel_api/__init__.py \
    && pip install .

WORKDIR /app
COPY apps/api /app
ENV PYTHONPATH=/app/src

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m lifereel_api.bootstrap && uvicorn lifereel_api.main:app --host 0.0.0.0 --port 8000"]
