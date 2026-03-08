FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir .
FROM base AS final
COPY app/ ./app/
# Run Celery worker AND beat scheduler
CMD ["celery", "-A", "app.celery_app", "worker", "-B", "--loglevel=info", "--concurrency=4"]
