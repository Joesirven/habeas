# Dataproc Serverless — DROP CA name arm (Arm A)

Requires `dataproc.googleapis.com` enabled and a GCS staging bucket
(`DATAPROC_STAGING_BUCKET`, default `gs://example-gcp-project-dataproc-staging`).

## Submit

```bash
chmod +x analytics/jobs/dataproc/submit.sh
./analytics/jobs/dataproc/submit.sh
```

Writes:

- `drop_hash_experiment.arm_spark_name_hash`
- `drop_hash_experiment.arm_spark_ndz_hash`
- metrics append to `arm_run_metrics`

## Local smoke (no cluster)

The job imports `drop_normalize`; vector gate is identical to pytest:

```bash
uv run pytest analytics/drop_normalize/tests/test_cppa_vectors_v120.py -q
```

## Future triggers

`gcloud dataproc batches submit` from Scheduler/Eventarc using the same script args.
