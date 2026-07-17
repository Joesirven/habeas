"""Cloud Run Job: normalize distinct CA names in Python, join in BigQuery for full tables."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from google.cloud import bigquery

from drop_normalize import hash_std, normalize_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("arm_cloudrun")

PROJECT = os.environ.get("GCP_PROJECT", "example-gcp-project")
DATASET = os.environ.get("EXPERIMENT_DATASET", "drop_hash_experiment")
STATE = os.environ.get("STATE", "CA")
ARM = os.environ.get("ARM", "cloudrun")
FLUSH_EVERY = int(os.environ.get("FLUSH_EVERY", "50000"))


def _fq(name: str) -> str:
    return f"{PROJECT}.{DATASET}.{name}"


def _sql(name: str) -> str:
    return f"`{_fq(name)}`"


def vector_ok() -> bool:
    fn = hash_std(normalize_name("Danielle"))
    ln = hash_std(normalize_name("Johnson"))
    return (
        hash_std(fn + ln + hash_std("19850704") + hash_std("91790"))
        == "PQOfn1RffEKmqMmNAzDKKaoZCwxWbQZkQzPWmQo9REA="
    )


def ensure_metrics_table(client: bigquery.Client) -> None:
    client.query(
        f"""
        CREATE TABLE IF NOT EXISTS {_sql("arm_run_metrics")} (
          arm STRING,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          wall_seconds FLOAT64,
          rows_in INT64,
          rows_out INT64,
          shard_count INT64,
          vector_ok BOOL,
          notes STRING
        )
        """
    ).result()


def _load(client: bigquery.Client, table_fq: str, rows: list[dict], schema: list) -> None:
    if not rows:
        return
    job = client.load_table_from_json(
        rows,
        table_fq,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        ),
    )
    job.result()


def build_name_dim(client: bigquery.Client, column: str, dim_table: str) -> int:
    """Normalize DISTINCT values of firstname or lastname into a dimension table."""
    client.delete_table(dim_table, not_found_ok=True)
    schema = [
        bigquery.SchemaField("raw_name", "STRING"),
        bigquery.SchemaField("name_std", "STRING"),
        bigquery.SchemaField("name_hash", "STRING"),
    ]
    client.create_table(bigquery.Table(dim_table, schema=schema))

    sql = f"""
    SELECT DISTINCT {column} AS raw_name
    FROM {_sql("stg_ca_person")}
    WHERE state = @state AND {column} IS NOT NULL AND {column} != ''
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("state", "STRING", STATE)]
    )
    buf: list[dict] = []
    n = 0
    for row in client.query(sql, job_config=job_config).result(page_size=FLUSH_EVERY):
        raw = row["raw_name"]
        std = normalize_name(raw)
        buf.append(
            {
                "raw_name": raw,
                "name_std": std,
                "name_hash": hash_std(std) if std else None,
            }
        )
        n += 1
        if len(buf) >= FLUSH_EVERY:
            _load(client, dim_table, buf, schema)
            buf.clear()
            log.info("dim %s progress %s", column, n)
    if buf:
        _load(client, dim_table, buf, schema)
    log.info("dim %s done distinct=%s", column, n)
    return n


def materialize_outputs(client: bigquery.Client) -> int:
    """Join person + dims + dob/zip hashes into arm_cloudrun_* tables."""
    name_sql = f"""
    CREATE OR REPLACE TABLE {_sql("arm_cloudrun_name_hash")} AS
    SELECT
      p.dwid,
      p.state,
      fn.name_std AS first_name_std,
      ln.name_std AS last_name_std,
      fn.name_hash AS first_name_hash,
      ln.name_hash AS last_name_hash
    FROM {_sql("stg_ca_person")} AS p
    LEFT JOIN {_sql("_dim_cloudrun_firstname")} AS fn
      ON p.firstname = fn.raw_name
    LEFT JOIN {_sql("_dim_cloudrun_lastname")} AS ln
      ON p.lastname = ln.raw_name
    WHERE p.state = '{STATE}'
    """
    client.query(name_sql).result()

    ndz_sql = f"""
    CREATE OR REPLACE TABLE {_sql("arm_cloudrun_ndz_hash")} AS
    SELECT
      n.dwid,
      n.state,
      CASE
        WHEN n.first_name_hash IS NOT NULL
         AND n.last_name_hash IS NOT NULL
         AND d.dob_hash IS NOT NULL
         AND z.zip_hash IS NOT NULL
        THEN TO_BASE64(SHA256(
          n.first_name_hash || n.last_name_hash || d.dob_hash || z.zip_hash
        ))
      END AS ndz_hash
    FROM {_sql("arm_cloudrun_name_hash")} AS n
    LEFT JOIN {_sql("int_ca_dob_hash")} AS d USING (dwid, state)
    LEFT JOIN {_sql("int_ca_zip_hash")} AS z USING (dwid, state)
    """
    client.query(ndz_sql).result()
    return next(
        client.query(f"SELECT COUNT(*) AS n FROM {_sql('arm_cloudrun_name_hash')}").result()
    )["n"]


def main() -> None:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    client = bigquery.Client(project=PROJECT)
    ensure_metrics_table(client)
    vok = vector_ok()
    if not vok:
        raise SystemExit("CPPA NDZ vector check failed — aborting")

    fn_n = build_name_dim(client, "firstname", _fq("_dim_cloudrun_firstname"))
    ln_n = build_name_dim(client, "lastname", _fq("_dim_cloudrun_lastname"))
    rows_out = materialize_outputs(client)

    finished = datetime.now(timezone.utc)
    wall = time.perf_counter() - t0
    client.query(
        f"""
        INSERT INTO {_sql("arm_run_metrics")}
        (arm, started_at, finished_at, wall_seconds, rows_in, rows_out, shard_count, vector_ok, notes)
        VALUES
        (@arm, @started, @finished, @wall, @rin, @rout, 1, @vok, @notes)
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("arm", "STRING", ARM),
                bigquery.ScalarQueryParameter("started", "TIMESTAMP", started),
                bigquery.ScalarQueryParameter("finished", "TIMESTAMP", finished),
                bigquery.ScalarQueryParameter("wall", "FLOAT64", wall),
                bigquery.ScalarQueryParameter("rin", "INT64", fn_n + ln_n),
                bigquery.ScalarQueryParameter("rout", "INT64", rows_out),
                bigquery.ScalarQueryParameter("vok", "BOOL", vok),
                bigquery.ScalarQueryParameter(
                    "notes",
                    "STRING",
                    f"distinct_fn={fn_n} distinct_ln={ln_n} dict+sql_join",
                ),
            ]
        ),
    ).result()
    log.info(
        "done arm=%s distinct_in=%s rows_out=%s wall_s=%.1f vector_ok=%s",
        ARM,
        fn_n + ln_n,
        rows_out,
        wall,
        vok,
    )


if __name__ == "__main__":
    main()
