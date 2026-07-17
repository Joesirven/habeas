# habeas-cli

Habeas command-line interface (Typer). Hybrid client:

- Write path: admin-api over HTTP
- Read path: SELECT-only database access for analysis

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
