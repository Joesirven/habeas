# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/habeas-privacy-core/ ./libs/habeas-privacy-core/
COPY app/auth0/ ./app/auth0/
COPY transform/external_hash/ ./transform/external_hash/
COPY transform/drop_hash/profiles.yml.example ./transform/external_hash/profiles.yml.example
RUN sed -e 's/^drop_hash:/external_hash:/' \
        -e 's/dataset: drop_hash_index/dataset: external_hash_index/' \
        transform/external_hash/profiles.yml.example > transform/external_hash/profiles.yml
RUN uv sync --frozen --no-dev --package auth0-worker

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/app/auth0/src"
ENV PYTHONUNBUFFERED=1
ENV EXTERNAL_HASH_DBT_DIR=/app/transform/external_hash
ENV DBT_PROFILES_DIR=/app/transform/external_hash
EXPOSE 8080
CMD ["uvicorn", "auth0.main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "app/auth0/src"]
