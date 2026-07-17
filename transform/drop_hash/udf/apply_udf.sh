#!/usr/bin/env bash
# Create/replace normalize_name JS UDF from normalize_name.js (bake-off winner body).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-${GCP_PROJECT:-example-gcp-project}}"
TMP="$(mktemp)"
python3 - "$ROOT/create_normalize_name_udf.sql" "$ROOT/normalize_name.js" "$TMP" "$PROJECT" <<'PY'
import pathlib, sys
sql_path, js_path, out_path, project = sys.argv[1:5]
sql = pathlib.Path(sql_path).read_text()
js = pathlib.Path(js_path).read_text()
if "__JS_BODY__" not in sql:
    raise SystemExit("placeholder __JS_BODY__ missing")
if "return normalizeName(value);" not in sql:
    raise SystemExit("expected return normalizeName(value) for bake-off UDF entrypoint")
sql = sql.replace("__JS_BODY__", js)
sql = sql.replace("example-gcp-project", project)
pathlib.Path(out_path).write_text(sql)
PY
bq query \
  --use_legacy_sql=false \
  --project_id="${PROJECT}" \
  --location=us-east4 \
  < "$TMP"
rm -f "$TMP"
echo "UDF ${PROJECT}.drop_hash_index.normalize_name applied."
