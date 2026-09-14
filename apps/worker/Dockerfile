FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app

COPY apps/worker /app
RUN pip install --no-cache-dir .

CMD ["lifereel-worker"]
