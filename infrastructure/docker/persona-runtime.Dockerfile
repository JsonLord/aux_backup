FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir '.[production]'
COPY services/persona_service/requirements.lock ./persona-requirements.lock
RUN pip install --no-cache-dir -r persona-requirements.lock
COPY services ./services
CMD ["uvicorn", "services.persona_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
