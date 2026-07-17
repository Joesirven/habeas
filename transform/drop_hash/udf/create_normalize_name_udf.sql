-- Persistent DROP v1.2.0 name UDF in the production hash-index dataset.
-- Source of truth for body: transform/drop_hash/udf/normalize_name.js
-- Apply with: ./udf/apply_udf.sh

CREATE SCHEMA IF NOT EXISTS `example-gcp-project.drop_hash_index`
OPTIONS (location = 'us-east4');

CREATE OR REPLACE FUNCTION `example-gcp-project.drop_hash_index.normalize_name`(value STRING)
RETURNS STRING
LANGUAGE js
OPTIONS (
  description = 'DROP v1.2.0 name standardization (JS port of drop_normalize)'
)
AS r"""
__JS_BODY__
return normalize_name(value);
""";
