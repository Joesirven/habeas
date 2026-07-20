# habeas-cli

Habeas command-line interface (Typer). Hybrid client:

- Write path: admin-api over HTTP (Identity-Aware Proxy bearer when `ADMIN_API_URL` is Cloud Run)
- Read path: SELECT-only database access for analysis

Remote admin-api (SA impersonation — user ADC cannot mint `--audiences`):

```bash
export ADMIN_API_URL=https://admin-api-dev-hsa55rg7ja-uk.a.run.app
export IAP_OAUTH_CLIENT_ID=95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com
export IAP_IMPERSONATE_SERVICE_ACCOUNT=95660886550-compute@developer.gserviceaccount.com
# optional prefetch:
export IAP_ID_TOKEN="$(gcloud auth print-identity-token \
  --audiences="$IAP_OAUTH_CLIENT_ID" \
  --impersonate-service-account="$IAP_IMPERSONATE_SERVICE_ACCOUNT" \
  --include-email)"
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
