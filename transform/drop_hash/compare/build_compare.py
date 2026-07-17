#!/usr/bin/env python3
"""Compare DROP hash CA experiment arms: metrics, vectors, cross-arm equality."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

PROJECT = "example-gcp-project"
DATASET = "drop_hash_experiment"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("tmp/drop-hash-ca-compare-report.md"),
    )
    args = parser.parse_args()
    client = bigquery.Client(project=PROJECT)

    metrics = list(
        client.query(
            f"""
            SELECT arm, started_at, finished_at, wall_seconds, rows_in, rows_out,
                   shard_count, vector_ok, notes
            FROM `{PROJECT}.{DATASET}.arm_run_metrics`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY arm ORDER BY started_at DESC) = 1
            ORDER BY arm
            """
        ).result()
    )
    if not metrics:
        print("ERROR: no arm_run_metrics rows", file=sys.stderr)
        return 1

    arms_present = {m["arm"] for m in metrics}
    required = {"udf", "spark", "cloudrun"}
    missing_metrics = required - arms_present

    tables = {
        "udf": f"{PROJECT}.{DATASET}.arm_udf_ndz_hash",
        "spark": f"{PROJECT}.{DATASET}.arm_spark_ndz_hash",
        "cloudrun": f"{PROJECT}.{DATASET}.arm_cloudrun_ndz_hash",
    }
    counts = {}
    for arm, table in tables.items():
        try:
            counts[arm] = next(
                client.query(f"SELECT COUNT(*) AS n FROM `{table}`").result()
            )["n"]
        except Exception as exc:  # noqa: BLE001
            counts[arm] = None
            print(f"WARN: count failed for {arm}: {exc}", file=sys.stderr)

    # Cross-arm equality on overlapping keys (sample or full if tables exist)
    equality_sql = f"""
    WITH
      u AS (SELECT dwid, state, ndz_hash FROM `{tables['udf']}` WHERE ndz_hash IS NOT NULL),
      s AS (SELECT dwid, state, ndz_hash FROM `{tables['spark']}` WHERE ndz_hash IS NOT NULL),
      c AS (SELECT dwid, state, ndz_hash FROM `{tables['cloudrun']}` WHERE ndz_hash IS NOT NULL)
    SELECT
      COUNT(*) AS overlap_rows,
      COUNTIF(u.ndz_hash = s.ndz_hash AND u.ndz_hash = c.ndz_hash) AS all_three_match,
      COUNTIF(u.ndz_hash = s.ndz_hash) AS udf_spark_match,
      COUNTIF(u.ndz_hash = c.ndz_hash) AS udf_cloudrun_match,
      COUNTIF(s.ndz_hash = c.ndz_hash) AS spark_cloudrun_match
    FROM u
    INNER JOIN s USING (dwid, state)
    INNER JOIN c USING (dwid, state)
    """
    equality = None
    try:
        if all(counts.get(a) for a in ("udf", "spark", "cloudrun")):
            equality = dict(next(client.query(equality_sql).result()))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: equality query failed: {exc}", file=sys.stderr)

    vector_fail = any(m["vector_ok"] is False for m in metrics)

    # Rough cost priors ($/TiB BQ on-demand ~$6.25; Dataproc DCU rough)
    lines = [
        f"# DROP hash CA experiment — compare report",
        f"",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Project: `{PROJECT}` · Dataset: `{DATASET}`",
        f"",
        f"## Metrics",
        f"",
        f"| arm | wall_s | rows_in | rows_out | vector_ok | notes |",
        f"|-----|--------|---------|----------|-----------|-------|",
    ]
    for m in metrics:
        lines.append(
            f"| {m['arm']} | {m['wall_seconds']} | {m['rows_in']} | {m['rows_out']} "
            f"| {m['vector_ok']} | {m['notes'] or ''} |"
        )

    lines += [
        f"",
        f"## Table row counts (NDZ)",
        f"",
        f"| arm | ndz rows |",
        f"|-----|----------|",
    ]
    for arm, n in counts.items():
        lines.append(f"| {arm} | {n} |")

    if equality:
        overlap = equality["overlap_rows"] or 0
        match = equality["all_three_match"] or 0
        pct = (100.0 * match / overlap) if overlap else 0.0
        lines += [
            f"",
            f"## Cross-arm NDZ equality",
            f"",
            f"- Overlap rows: **{overlap}**",
            f"- All three match: **{match}** ({pct:.4f}%)",
            f"- UDF↔Spark: {equality['udf_spark_match']}",
            f"- UDF↔Cloud Run: {equality['udf_cloudrun_match']}",
            f"- Spark↔Cloud Run: {equality['spark_cloudrun_match']}",
        ]
    else:
        lines += ["", "## Cross-arm NDZ equality", "", "_Skipped — missing arm tables or query error._"]

    if missing_metrics:
        lines += ["", f"## Gaps", "", f"Missing metrics for arms: {sorted(missing_metrics)}"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")

    if vector_fail:
        print("ERROR: vector_ok=false in metrics", file=sys.stderr)
        return 2
    if missing_metrics or any(counts.get(a) in (None, 0) for a in required):
        print("ERROR: incomplete arms for Definition of Done", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
