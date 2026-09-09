FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir '.[production]'
COPY apps ./apps
COPY alembic.ini ./alembic.ini
COPY infrastructure/migrations ./infrastructure/migrations
RUN mkdir -p /app/data/artifacts
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
