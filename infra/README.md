# Cloud Build + Artifact Registry

| File | Purpose |
|------|---------|
| [`cloudbuild/reaper.yaml`](cloudbuild/reaper.yaml) | Test, build, migrate, deploy `reaper` |
| [`cloudbuild/trigger-reaper.yaml`](cloudbuild/trigger-reaper.yaml) | Trigger definition (path-filtered) |

**Project:** `example-gcp-project` · **Region:** `us-east4` · **Artifact Registry repo:** `data-privacy`

## One-time setup

```bash
gcloud artifacts repositories create data-privacy \
  --repository-format=docker \
  --location=us-east4 \
  --project=example-gcp-project

# Secret for Cloud Build migrations + Cloud Run runtime
echo -n 'postgres://…' | gcloud secrets create database-url \
  --data-file=- \
  --project=example-gcp-project
```

Wire the Cloud Build trigger using `cloudbuild/trigger-reaper.yaml` after connecting the Bitbucket repo.

## Manual deploy (dev)

```bash
gcloud builds submit --config=infra/cloudbuild/reaper.yaml --project=example-gcp-project .
```
