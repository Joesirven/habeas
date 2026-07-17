"""
Dataproc Serverless PySpark: CA names via distinct + mapPartitions normalize.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from drop_normalize import hash_std, normalize_name

PROJECT = "example-gcp-project"
DATASET = "drop_hash_experiment"
TEMP_BUCKET = "example-gcp-project-dataproc-staging"


def _normalize_partition(rows):
    for row in rows:
        raw = row[0]
        if raw is None:
            continue
        std = normalize_name(raw)
        yield (raw, std, hash_std(std) if std else None)


def main() -> None:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    spark = (
        SparkSession.builder.appName("drop-hash-ca-spark-names")
        .config("spark.datasource.bigquery.viewsEnabled", "true")
        .getOrCreate()
    )

    fn = hash_std(normalize_name("Danielle"))
    ln = hash_std(normalize_name("Johnson"))
    vok = (
        hash_std(fn + ln + hash_std("19850704") + hash_std("91790"))
        == "PQOfn1RffEKmqMmNAzDKKaoZCwxWbQZkQzPWmQo9REA="
    )
    if not vok:
        raise SystemExit("CPPA NDZ vector check failed")

    person = (
        spark.read.format("bigquery")
        .option("table", f"{PROJECT}.{DATASET}.stg_ca_person")
        .load()
        .select("dwid", "state", "firstname", "lastname")
    )

    schema = StructType(
        [
            StructField("raw_name", StringType(), True),
            StructField("name_std", StringType(), True),
            StructField("name_hash", StringType(), True),
        ]
    )

    def dim_for(column: str):
        return (
            person.select(column)
            .distinct()
            .rdd.mapPartitions(_normalize_partition)
            .toDF(schema)
            .withColumnRenamed("raw_name", column)
        )

    fn_dim = dim_for("firstname")
    ln_dim = dim_for("lastname")

    names = (
        person.join(fn_dim, on="firstname", how="left")
        .withColumnRenamed("name_std", "first_name_std")
        .withColumnRenamed("name_hash", "first_name_hash")
        .join(ln_dim, on="lastname", how="left")
        .withColumnRenamed("name_std", "last_name_std")
        .withColumnRenamed("name_hash", "last_name_hash")
        .select(
            "dwid",
            "state",
            "first_name_std",
            "last_name_std",
            "first_name_hash",
            "last_name_hash",
        )
    )

    (
        names.write.format("bigquery")
        .option("table", f"{PROJECT}.{DATASET}.arm_spark_name_hash")
        .option("temporaryGcsBucket", TEMP_BUCKET)
        .option("writeMethod", "indirect")
        .mode("overwrite")
        .save()
    )

    dob = (
        spark.read.format("bigquery")
        .option("table", f"{PROJECT}.{DATASET}.int_ca_dob_hash")
        .load()
        .select("dwid", "state", "dob_hash")
    )
    zip_h = (
        spark.read.format("bigquery")
        .option("table", f"{PROJECT}.{DATASET}.int_ca_zip_hash")
        .load()
        .select("dwid", "state", "zip_hash")
    )

    ndz = (
        names.join(dob, ["dwid", "state"], "left")
        .join(zip_h, ["dwid", "state"], "left")
        .withColumn(
            "ndz_hash",
            F.when(
                F.col("first_name_hash").isNotNull()
                & F.col("last_name_hash").isNotNull()
                & F.col("dob_hash").isNotNull()
                & F.col("zip_hash").isNotNull(),
                F.base64(
                    F.unhex(
                        F.sha2(
                            F.concat(
                                F.col("first_name_hash"),
                                F.col("last_name_hash"),
                                F.col("dob_hash"),
                                F.col("zip_hash"),
                            ),
                            256,
                        )
                    )
                ),
            ),
        )
        .select("dwid", "state", "ndz_hash")
    )
    (
        ndz.write.format("bigquery")
        .option("table", f"{PROJECT}.{DATASET}.arm_spark_ndz_hash")
        .option("temporaryGcsBucket", TEMP_BUCKET)
        .option("writeMethod", "indirect")
        .mode("overwrite")
        .save()
    )

    rows_in = names.count()
    rows_out = ndz.count()
    wall = time.perf_counter() - t0
    finished = datetime.now(timezone.utc)
    metrics = spark.createDataFrame(
        [
            {
                "arm": "spark",
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "wall_seconds": float(wall),
                "rows_in": int(rows_in),
                "rows_out": int(rows_out),
                "shard_count": 1,
                "vector_ok": bool(vok),
                "notes": "dataproc mapPartitions distinct-dict+join; indirect BQ write",
            }
        ]
    )
    (
        metrics.write.format("bigquery")
        .option("table", f"{PROJECT}.{DATASET}.arm_run_metrics")
        .option("temporaryGcsBucket", TEMP_BUCKET)
        .option("writeMethod", "indirect")
        .mode("append")
        .save()
    )
    spark.stop()


if __name__ == "__main__":
    main()
