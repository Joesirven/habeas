> inherits: ../AGENTS.md

# AGENTS.md — infra/

Cloud Build pipelines, Terraform, Docker build contexts. Path-filtered triggers: rebuild app when `libs/habeas-privacy-core` or that app changes.

## Rules

- Cloud Build only — no external continuous integration (per architecture decision 15).
- Run `dbmate up` before Cloud Run deploy.
- **Identity (Architecture B — prod web path):** Cloud Run IAP is **off** on `admin-api` (`--no-iap`). `REQUIRE_IAP_IDENTITY=true`; `resolve_actor` needs a verified Bearer (`user_jwt` / `bearer_jwt` / `iap_header`); header-alone → 401. Live `admin-api-prod` invoker **matches** live `admin-api-dev`: `allUsers` + compute SA + `jsirven@` so GIS JWT can reach the resource server — this **copies DEV**, it does not invent `allUsers`. The app still verifies the JWT (`aud` = OAuth client). [`admin-web-prod.yaml`](cloudbuild/admin-web-prod.yaml) bakes `VITE_ADMIN_API_URL` to `admin-api-prod`; GSM `iap-oauth-client-id` supplies `VITE_GOOGLE_CLIENT_ID` at deploy. `admin-web` IAP stays the human SSO front door; nginx `/api` remains for Server-Sent Events. CLI: `habeas-cli auth login --adc` or `auth login` (`ADMIN_API_ID_TOKEN_AUDIENCE` + `IAP_OAUTH_CLIENT_ID`). Workers: admin-api runtime SA invoker only — never user/IAP direct. Do **not** re-enable Cloud Run IAP on admin-api. Do **not** run [`admin-api-dev-iam.yaml`](cloudbuild/admin-api-dev-iam.yaml) (turns IAP on).
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
