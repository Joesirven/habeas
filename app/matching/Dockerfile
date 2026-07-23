# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/habeas-privacy-core/ ./libs/habeas-privacy-core/
COPY app/matching/ ./app/matching/
RUN uv sync --frozen --no-dev --package matching-worker

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/app/matching/src"
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "matching.main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "app/matching/src"]
