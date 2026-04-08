FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
FROM base AS final
COPY app/ ./app/
COPY proto/ ./proto/
EXPOSE 8000 50051
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
