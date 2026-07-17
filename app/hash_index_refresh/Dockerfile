# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/habeas-privacy-core/ ./libs/habeas-privacy-core/
COPY app/hash_index_refresh/ ./app/hash_index_refresh/
COPY transform/drop_hash/ ./transform/drop_hash/
# profiles.yml is gitignored; bake the oauth example so Cloud Run dbt can find it.
RUN cp transform/drop_hash/profiles.yml.example transform/drop_hash/profiles.yml
RUN uv sync --frozen --no-dev --package hash-index-refresh

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV DROP_HASH_DBT_DIR=/app/transform/drop_hash
ENV DBT_PROFILES_DIR=/app/transform/drop_hash
EXPOSE 8080
CMD ["uvicorn", "hash_index_refresh.main:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "app/hash_index_refresh/src"]
