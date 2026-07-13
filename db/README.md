# db/

Database schema for the privacy automation system.

| Path | Purpose |
|------|---------|
| `migrations/` | dbmate SQL — all tables (core, matching, per-system attempts, audit) |

One Postgres instance — one migration folder. Per-app tables use filename scope prefixes, not subdirectories.

**Agent rules:** [`AGENTS.md`](AGENTS.md)
