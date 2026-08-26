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
  `POST /ensure-drain`. Prod templates: `data-vertical-matching-prod.yaml` (not
  live until prod Cloud SQL exists). Job invoker = matching runtime SA
  (`roles/run.developer` on Job).
- **Jose-gated cutover:** live Cloud Run is still `matching-dev`. Admin-api-dev
  `_MATCHING_URL` may keep the current `matching-dev` `*.run.app` until Jose
  flips it — do not invent a new URL.

Prod deploy → [`.agent/modules/prod-write-gate.md`](../.agent/modules/prod-write-gate.md).
