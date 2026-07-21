# RUNBOOK — DROP hash index refresh (dbt)

Operator steps for production hash-index rebuild in `example-gcp-project.drop_hash_index`.

**Canonical dbt path:** `transform/drop_hash/` only. Do not `cd analytics` for production
refresh — that tree was the pre-migration CA bake-off sandbox.

## Serving schema

| BigQuery table | Columns |
|----------------|---------|
| `example-gcp-project.drop_hash_index.email_hash` | `hash_value`, `dwid`, `state`, `built_at` |
| `example-gcp-project.drop_hash_index.phone_hash` | same |
| `example-gcp-project.drop_hash_index.ndz_hash` | same |

All three are clustered on `(state, hash_value)`. Matching lookups use `hash_value` + `state`.

## Prerequisites

- ADC / service account with BigQuery Data Editor on `drop_hash_index`, read on `person_db`
- `normalize_name` UDF deployed (see `udf/README.md`)

## 1. Normalize package tests (optional gate)

```bash
cd transform/drop_hash/drop_normalize
uv run pytest tests -q
```

## 2. Apply / refresh name UDF

```bash
./transform/drop_hash/udf/apply_udf.sh
bq query --use_legacy_sql=false < transform/drop_hash/udf/tests/test_udf_vectors.sql
```

Expect **0 rows** from the vector query.

## 3. Per-state refresh (durable int/build → patch serving)

Shared serving marts hold all served states; each dbt run rebuilds **one** state
only — it does **not** re-hash the other 50.

| Layer | Physical tables (example `state=CA`) | Lifetime |
|-------|--------------------------------------|----------|
| Staging / int | `stg_person_ca`, `int_email_hash_ca`, `int_phone_hash_ca`, `int_ndz_hash_ca`, … | Durable; overwritten only when that state refreshes |
| Mart build | `email_hash__build_ca`, `phone_hash__build_ca`, `ndz_hash__build_ca` | Durable; retained after serving merge (parallel-safe) |
| Serving (national) | `email_hash`, `phone_hash`, `ndz_hash` | Patched: `DELETE`/`INSERT` (or first-create `COPY`) for `WHERE state='CA'` only |

```bash
cd transform/drop_hash
cp profiles.yml.example profiles.yml   # if needed
DBT_PROFILES_DIR=. dbt build --vars '{state: CA}'
DBT_PROFILES_DIR=. dbt build --vars '{state: TX}'
# Or enqueue one state / full wave via admin-api:
#   POST /ops/drop/hash-index-refresh/enqueue   (body: state)
#   POST /ops/drop/hash-index-refresh/enqueue-all
```

Flow for a single-state refresh (e.g. CA):

1. `generate_alias_name` suffixes every model alias with `_<state>` so parallel
   workers cannot clobber each other (FL phone race lesson).
2. Staging filters MDR with `state = var('state')`; int models hash that slice.
3. Mart models write `*_hash__build_<state>`.
4. `perform_serving_swap()` patches national serving for that state only and
   **keeps** the build tables (first create uses `CREATE TABLE … COPY`, not rename).

Parallel per-state jobs are OK; watch BigQuery slots/cost. Served-state list is
**USPS 50 + DC** (settled). Dry-run without patching serving:
`--vars '{state: CA, perform_serving_swap: false}'`.

**Timeout (name UDF):** chunk by `FARM_FINGERPRINT(dwid) % N` — see `udf/README.md`.

## 4. Verify serving row counts

```bash
bq query --use_legacy_sql=false '
SELECT "email_hash" AS mart, COUNT(*) AS rows FROM `example-gcp-project.drop_hash_index.email_hash`
UNION ALL SELECT "phone_hash", COUNT(*) FROM `example-gcp-project.drop_hash_index.phone_hash`
UNION ALL SELECT "ndz_hash", COUNT(*) FROM `example-gcp-project.drop_hash_index.ndz_hash`
'
```

## Experiment sandbox (non-prod)

CA bake-off artifacts may still exist in BigQuery dataset `drop_hash_experiment`
(historical code lived under `analytics/` on pre-migration branches). That dataset
and any local experiment worktrees are **not** part of this production dbt project.

## Live multi-state builds (A10)

**Allowlist (settled):** USPS 50 states + DC (**51** codes) in
`habeas_privacy_core.geo.state.USPS_STATES_PLUS_DC`. That list is the prod
source of truth for enqueue-all / hash refresh — not a separate MDR jurisdiction
config. Every state must be hashed and ready to match; sparse marts (email) still
run per state and simply yield zero serving rows when MDR has no values.

### Email MDR source (investigation 2026-07-20)

| Finding | Detail |
|---------|--------|
| Dataset | `example-gcp-project.person_db` (dbt `source('person_db', …)`) |
| Email tables | **None** named email/contact — only `person` holds an email field |
| Email column | Sole column: `person.emailaddress` (join keys `dwid`, `state`) |
| Other “mail*” columns | Postal/mail **address** fields on `person` / household / models — not emails |
| Phones | Separate table `phones` (`dwid`, `state`, cell/land) — no email columns |
| Fill rate | ~9.9M nonempty / ~377M person rows (~97% null or empty) |
| States with any email | **9:** NY, IN, IL, WI, RI, SD, FL, AZ, MT — remaining 42 (incl. **CA**) have zero nonempty |
| dbt recommendation | Keep `stg_person` → `int_email_hash` on `emailaddress`; **no union** needed |

Sparse `email_hash` is an MDR completeness property, not a wrong dbt source.

**Enqueue-all wave (code complete — do not fire against prod without Jose):**

All enqueue/process calls go through **admin-api behind Identity-Aware Proxy**.
Do not curl workers, grant yourself worker `run.invoker`, or use `DATABASE_URL` for
mutations. Empty `POST /enqueue` does **not** default to CA — use `--state` or
`--all-states` / `enqueue-all`. See `infra/README.md` (“Calling admin-api with IAP”).

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
export IAP_OAUTH_CLIENT_ID=95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com
export IAP_IMPERSONATE_SERVICE_ACCOUNT=95660886550-compute@developer.gserviceaccount.com
export IAP_ID_TOKEN="$(gcloud auth print-identity-token \
  --audiences="$IAP_OAUTH_CLIENT_ID" \
  --impersonate-service-account="$IAP_IMPERSONATE_SERVICE_ACCOUNT" \
  --include-email)"
curl -sS -H "Authorization: Bearer $IAP_ID_TOKEN" "$ADMIN_API_URL/auth/me"
```

| Surface | Entry |
|---------|--------|
| Admin-api | `POST /ops/drop/hash-index-refresh/enqueue-all` (IAP bearer) → `enqueue_hash_index_refresh_all_states` |
| Web | Drop ops → Pipeline → Configurations → **Enqueue all states** (local: Vite `/api`; remote needs IAP) |
| CLI | `habeas-cli drop hash-index-refresh enqueue --all-states --execute` with `ADMIN_API_URL` + IAP SA token |
| Process | `habeas-cli drop hash-index-refresh process --execute` (admin-api proxies the worker; never call worker `/process` as a user) |
| Worker | Invoked only by admin-api runtime SA (`roles/run.invoker` on workers — never user/IAP) |

Parallel per-state `dbt build --vars '{state: …}'` into shared serving marts is
supported (staging/int/build relations are state-suffixed and **retained** after
the serving patch). Watch BigQuery slots/cost. Prefer the queue/worker path over
ad-hoc prod dbt. See “Per-state refresh” above.

**FL phone gap (2026-07-17):** After the first enqueue-all wave, `phone_hash`
had every served state except `FL` while MDR `person_db.phones` had ~20.5M FL
rows and `ndz_hash` retained FL — caused by shared unsuffixed `*_hash__build`
tables racing under parallel workers. Fixed via state-suffixed aliases; re-enqueue
FL only after the fix is deployed:

```bash
# Requires IAP SA token (see copy-paste block above) — not DATABASE_URL.
habeas-cli drop hash-index-refresh enqueue --state FL --execute
```

### Read-only BQ probe (2026-07-20, operator ADC)

Project `example-gcp-project` · `bq ls` / metadata + count queries OK (no PII selected).

| Mart | Row count | Distinct `state` | Notes |
|------|-----------|------------------|--------|
| `email_hash` | ~9.91M | **9** | Exact match to MDR nonempty `person.emailaddress`; states NY/IN/IL/WI/RI/SD/FL/AZ/MT. CA and 41 others correctly absent (MDR zero fill). |
| `phone_hash` | ~411.7M | **51** | Full USPS 50+DC coverage |
| `ndz_hash` | ~276.9M | **51** | Full USPS 50+DC coverage |

Dataset `drop_hash_index` lists serving + intermediate tables; experiment dataset
`drop_hash_experiment` still present (sandbox only). No re-enqueue needed for
email after the 2026-07-20 investigation — serving already equals MDR fill.

### Blockers / notes for prod enqueue-all

1. **Prod-write gate** — no prod dbt build and no prod `enqueue-all` without Jose
   approval (see `.agent/modules/prod-write-gate.md`). Prior waves approved separately.
2. **Served states** — **settled:** USPS 50+DC. Re-enqueue only when MDR updates or
   a mart gap appears (phone/ndz currently 51/51).
3. **Email sparsity** — expected; not a rebuild blocker. Matching on email only
   works in the 9 MDR-filled states until Habeas loads more `emailaddress` values.
4. **Worker workload identity** — Cloud Build does not yet attach a dedicated
   `hash-index-refresh` runtime SA with BigQuery `jobUser` + dataset write on
   `drop_hash_index` + MDR read (see `infra/README.md` go-live checklist). Invoker
   IAM for admin-api → worker is separate (`hash-index-refresh-dev-iam.yaml`).
5. **Ops tooling gap (local)** — `gcloud run services describe` may fail if the
   local Cloud SDK Python env lacks `grpc`; use a healthy `gcloud` / Cloud Console
   to verify the worker SA. Does not block `bq` metadata probes.

## Future triggers

| Entrypoint | Invoker |
|------------|---------|
| `dbt build --vars '{state: <STATE>}'` from `transform/drop_hash/` | Hash-index refresh worker (`app/hash_index_refresh`) — rematch-on-refresh for that state |
| `POST /ops/drop/hash-index-refresh/enqueue-all` | Admin-api full wave (A10 allowlist = USPS 50+DC; Jose before prod) |
| `./udf/apply_udf.sh` | When `normalize_name.js` changes |
