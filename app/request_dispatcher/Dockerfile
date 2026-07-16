# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/habeas-privacy-core/ ./libs/habeas-privacy-core/
COPY app/request_dispatcher/ ./app/request_dispatcher/
RUN uv sync --frozen --no-dev --package request-dispatcher

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "request_dispatcher.main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "app/request_dispatcher/src"]
