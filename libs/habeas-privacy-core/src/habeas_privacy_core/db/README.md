# db/

asyncpg pool, migrations, and table helpers (`requests`, DROP/manual promote helpers,
`hash_index_refresh`, rematch).

- Per-state hash-index enqueue + `enqueue_hash_index_refresh_all_states`
- Rematch-on-refresh for open DROP whose normalized `requestor_state` matches the refreshed state
- State codes via `habeas_privacy_core.geo.normalize_state_acronym`

Part of [`habeas-privacy-core`](../../../).

**Agent rules:** [`AGENTS.md`](AGENTS.md)
