#!/usr/bin/env bash
# Create/replace normalize_name JS UDF from normalize_name.js
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp)"
python3 - "$ROOT/create_normalize_name_udf.sql" "$ROOT/normalize_name.js" "$TMP" <<'PY'
import pathlib, sys
sql_path, js_path, out_path = sys.argv[1:4]
sql = pathlib.Path(sql_path).read_text()
js = pathlib.Path(js_path).read_text()
if "__JS_BODY__" not in sql:
    raise SystemExit("placeholder __JS_BODY__ missing")
pathlib.Path(out_path).write_text(sql.replace("__JS_BODY__", js))
PY
bq query --use_legacy_sql=false --project_id=example-gcp-project < "$TMP"
rm -f "$TMP"
echo "UDF example-gcp-project.drop_hash_index.normalize_name applied."
