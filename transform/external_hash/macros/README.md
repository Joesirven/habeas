# Macros — build + swap (planned)

Per-system serving marts will mirror `transform/drop_hash/macros/swap_serving_tables.sql`:

1. **Durable build tables** — mart models write to `*_hash__build` aliases (see
   `mart_auth0_email_hash.sql` → `auth0_email_hash__build`).
2. **`perform_serving_swap()` on-run-end** — after a successful `dbt build` for one
   system, copy or merge the build into the shared serving table
   (`auth0_email_hash`, `axios_headquarters_email_hash`, `paylocity_email_hash`, …).
3. **Per-system isolation** — unlike DROP’s state suffix, external verticals scope
   by `system` column and/or system-prefixed physical table names so parallel
   hash-refresh workers do not clobber each other.

External marts do **not** use `var('state')`; serving columns are
`(hash_value, vendor_record_id, system, built_at)`.

When implementing swap macros:

- Follow `drop_hash` merge semantics (first create via `CREATE TABLE … COPY`, later
  refreshes `DELETE`/`INSERT` filtered by `system`).
- Gate with `var('perform_serving_swap', true)`; disable for dry runs.
- Never add models that read plaintext vendor fields — sources are already hashed.
