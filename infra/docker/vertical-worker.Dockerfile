# syntax=docker/dockerfile:1
# Shared image for external vertical workers (mailchimp, paylocity, lever, auth0, google_sheets).
# Build with --build-arg WORKER_PACKAGE / WORKER_MODULE / UVICORN_APP_DIR.

ARG WORKER_PACKAGE=mailchimp-worker
ARG WORKER_MODULE=mailchimp
ARG UVICORN_APP_DIR=app/mailchimp/src

FROM python:3.12-slim AS builder
ARG WORKER_PACKAGE
ARG WORKER_MODULE
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/habeas-privacy-core/ ./libs/habeas-privacy-core/
COPY app/${WORKER_MODULE}/ ./app/${WORKER_MODULE}/
COPY transform/external_hash/ ./transform/external_hash/
RUN cp transform/external_hash/profiles.yml.example transform/external_hash/profiles.yml
RUN uv sync --frozen --no-dev --package ${WORKER_PACKAGE}

FROM python:3.12-slim
ARG WORKER_MODULE
ARG UVICORN_APP_DIR
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV EXTERNAL_HASH_DBT_DIR=/app/transform/external_hash
ENV DBT_PROFILES_DIR=/app/transform/external_hash
EXPOSE 8080
CMD uvicorn ${WORKER_MODULE}.main:app --host 0.0.0.0 --port 8080 --app-dir ${UVICORN_APP_DIR}
