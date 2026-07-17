# Compare report

```bash
cd /Users/jsirven/Habeas/data-privacy
uv run --with google-cloud-bigquery python transform/drop_hash/compare/build_compare.py
```

Writes `tmp/drop-hash-ca-compare-report.md` (gitignored). Exit code non-zero if vectors
failed or an arm table/metrics row is missing.
