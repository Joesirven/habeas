# auth/

Identity-Aware Proxy identity helpers for admin-api.

| Helper | Role |
|--------|------|
| `parse_iap_email` | Strip `accounts.google.com:` prefix from IAP email header |
| `actor_from_iap_header` | Actor string for audit / mutation attribution (`unknown` if missing) |
| `is_authenticated_actor` | True when actor is not the unknown placeholder |

Admin-api DROP mutations use `REQUIRE_IAP_IDENTITY` + `require_drop_mutation_actor` (see `admin_api.drop_pipeline`). Full IAP JWT assertion verification remains a follow-up when the OAuth client audience is provisioned.

Part of [`habeas-privacy-core`](../../../).

**Agent rules:** [`AGENTS.md`](AGENTS.md)
