# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

COPY analytics/drop_normalize /tmp/drop_normalize
RUN pip install --no-cache-dir /tmp/drop_normalize google-cloud-bigquery==3.27.0

COPY analytics/jobs/cloudrun/main.py /app/main.py

ENV PYTHONUNBUFFERED=1
ENV ARM=cloudrun
ENV STATE=CA
ENV GCP_PROJECT=example-gcp-project
ENV EXPERIMENT_DATASET=drop_hash_experiment

CMD ["python", "/app/main.py"]
