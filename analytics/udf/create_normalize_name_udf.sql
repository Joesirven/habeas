-- Persistent DROP v1.2.0 name UDF in the experiment dataset.
-- Source of truth for body: analytics/udf/normalize_name.js
-- Apply with: bq query --use_legacy_sql=false < analytics/udf/create_normalize_name_udf.sql
-- (or the apply script in README which inlines the JS file)

CREATE SCHEMA IF NOT EXISTS `example-gcp-project.drop_hash_experiment`
OPTIONS (location = 'us-east4');

CREATE OR REPLACE FUNCTION `example-gcp-project.drop_hash_experiment.normalize_name`(value STRING)
RETURNS STRING
LANGUAGE js
OPTIONS (
  description = 'DROP v1.2.0 name standardization (JS port of drop_normalize)'
)
AS r"""
__JS_BODY__
return normalize_name(value);
""";
