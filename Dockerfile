FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.13-slim AS api
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend backend
COPY services services
COPY config config
COPY .default-mode .default-mode
COPY fixtures fixtures
COPY recordings recordings
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/backend:/app
RUN mkdir /data && chown 65534:65534 /data
USER 65534:65534
CMD ["uvicorn", "lab.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM api AS runner
USER root
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
CMD ["uvicorn", "services.runner:app", "--host", "0.0.0.0", "--port", "8003", "--no-access-log"]

FROM python:3.13-alpine AS task
COPY services/inspect.py /inspect.py
COPY runner-fixtures /fixtures
USER 65534:65534
CMD ["python", "/inspect.py"]
