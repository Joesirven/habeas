# habeas-cli

Habeas command-line interface (Typer). Hybrid client:

- Write path: admin-api over HTTP (Identity-Aware Proxy bearer when `ADMIN_API_URL` is Cloud Run)
- Read path: SELECT-only database access for analysis

Remote admin-api:

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
export IAP_OAUTH_CLIENT_ID=<iap-oauth-client-id>
# or: export IAP_ID_TOKEN="$(gcloud auth print-identity-token --audiences=$IAP_OAUTH_CLIENT_ID)"
```

DROP spine proxies (mutations require `--execute`; dry-run otherwise):

```bash
habeas-cli drop pipeline
habeas-cli drop download --execute
habeas-cli drop land [--gcs-uri URI] [--land-attempt-id N] --execute
habeas-cli drop promote [--limit N] --execute
habeas-cli drop dispatch [--limit N] --execute
habeas-cli drop match --execute
habeas-cli drop fulfill [--request-id ID] [--limit N] --execute
habeas-cli drop hash-index-refresh enqueue|process|status
```

**Agent rules:** [`AGENTS.md`](AGENTS.md)
