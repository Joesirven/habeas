> inherits: ../AGENTS.md

# AGENTS.md — infra/

Cloud Build pipelines, Terraform, Docker build contexts. Path-filtered triggers: rebuild app when `libs/habeas-privacy-core` or that app changes.

## Rules

- Cloud Build only — no external continuous integration (per architecture decision 15).
- Run `dbmate up` before Cloud Run deploy.
- **Identity (Architecture B — intended; CLI path current; browser GIS not prod):** Cloud Run IAP is **off** on `admin-api` (`--no-iap`). Cloud Build admin-api yamls: `--no-allow-unauthenticated`, `--no-iap`, `REQUIRE_IAP_IDENTITY=true`, fail-closed `allUsers` strip (not `|| true`). Live invoker on `admin-api-prod` and `admin-api-dev`: compute SA + `jsirven@` only — `allUsers` is **stripped**. Do **not** say `allUsers` stays so GIS can reach the API. GIS JWT `aud` is the OAuth client, not the Cloud Run URL; a prod-web 00024 flip today would **403** at IAM. `resolve_actor` rejects IAP email header alone (needs verified Bearer; header-alone → 401). CLI: `habeas-cli auth login --adc` or `auth login` (`ADMIN_API_ID_TOKEN_AUDIENCE` + `IAP_OAUTH_CLIENT_ID`). Browser GIS is **intended**, not live: prod web 100% is `admin-web-prod-00023-fnz` (nginx `/api`); **00024** is the unused B bake at 0% — do not flip until GIS `/me` is proven on DEV. `admin-web` remains the human SSO front door (IAP on). Server-Sent Events stay same-origin `/api/live/events`. Workers: admin-api runtime SA invoker only — never user/IAP direct. Do **not** re-enable Cloud Run IAP on admin-api. Do **not** run [`admin-api-dev-iam.yaml`](cloudbuild/admin-api-dev-iam.yaml) (turns IAP on).
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
