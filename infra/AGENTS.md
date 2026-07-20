> inherits: ../AGENTS.md

# AGENTS.md — infra/

Cloud Build pipelines, Terraform, Docker build contexts. Path-filtered triggers: rebuild app when `libs/habeas-privacy-core` or that app changes.

## Rules

- Cloud Build only — no external continuous integration (per architecture decision 15).
- Run `dbmate up` before Cloud Run deploy.
- Identity-Aware Proxy on `admin-api` (required; invoker = IAP SA only, `REQUIRE_IAP_IDENTITY=true`) and `admin-web` (SSO front door). Workers: admin-api runtime SA invoker only — never user/IAP direct.

Prod deploy → [`.agent/modules/prod-write-gate.md`](../.agent/modules/prod-write-gate.md).
