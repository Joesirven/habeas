> inherits: ../AGENTS.md

# AGENTS.md — app/request_dispatcher/

**Kind:** automation

Enqueues `matching_attempts` for thin `requests` that have none yet. Does not promote DROP raws and does not run matching.

- `POST /dispatch` — find requests without matching attempts → `enqueue_matching`
- Matching payload resolution stays in `app/matching/` via `request_resolver`
- Fulfillment gating via `matching.review` lives in admin-api / workflow helpers (U9 consumes)
- Vertical enqueue list types: `DISPATCH_VERTICAL_LIST_TYPES` (comma-separated
  `Email`, `Phone`, `NDZ`). **Default is Email only** so a deploy does not flood
  Phone/NDZ before marts are ready. Cutover order:
  [`transform/external_hash` README](../../transform/external_hash/README.md#phonendz-cutover-order)
  — do not duplicate here.

Schema in [`db/migrations/`](../../db/migrations/).
