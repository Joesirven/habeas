> inherits: ../AGENTS.md

# AGENTS.md — infra/

Cloud Build pipelines, Terraform, Docker build contexts. Path-filtered triggers: rebuild app when `libs/habeas-privacy-core` or that app changes.

## Rules

- Cloud Build only — no external continuous integration (per architecture decision 15).
- Run `dbmate up` before Cloud Run deploy.
- Identity-Aware Proxy on `admin-api` (required; invoker = IAP SA only, `REQUIRE_IAP_IDENTITY=true`) and `admin-web` (SSO front door). Workers: admin-api runtime SA invoker only — never user/IAP direct.
- Matching drain Job: `infra/cloudbuild/data-vertical-matching-dev.yaml` deploys
  service `data-vertical-matching-dev` + Job `data-vertical-matching-drain-dev`
  (tasks=5). App slug stays `matching`. Scheduler `dpra-dev-matching` → matching
  `POST /ensure-drain`. **Prod** is live via `data-vertical-matching-prod.yaml` +
  Job `data-vertical-matching-drain-prod`; `admin-api-prod` `_MATCHING_URL` points
  at `data-vertical-matching-prod` (not legacy `matching-prod`). Job invoker =
  matching runtime SA (`roles/run.developer` on Job).
- **Dev cutover (Jose-gated):** admin-api-dev `_MATCHING_URL` may still target legacy
  `matching-dev` until Jose flips it to `data-vertical-matching-dev` — do not invent
  a new URL.

Prod deploy → [`.agent/modules/prod-write-gate.md`](../.agent/modules/prod-write-gate.md).
