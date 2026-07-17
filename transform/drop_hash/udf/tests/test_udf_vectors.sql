-- Official DROP v1.2.0 name / NDZ vectors against the persistent UDF.
-- Fails (returns rows) when any assertion mismatches.

WITH cases AS (
  SELECT 'juan_pablo' AS case_id,
    `example-gcp-project.drop_hash_index.normalize_name`('Juan Pablo') AS got_std,
    'juanpablo' AS want_std,
    TO_BASE64(SHA256(`example-gcp-project.drop_hash_index.normalize_name`('Juan Pablo'))) AS got_hash,
    '91hIbrbzNeqHs3o81O5yNrXUj7wDd2shvZ6THKi9qz8=' AS want_hash
  UNION ALL
  SELECT 'martinez',
    `example-gcp-project.drop_hash_index.normalize_name`('Martinez'),
    'martinez',
    TO_BASE64(SHA256(`example-gcp-project.drop_hash_index.normalize_name`('Martinez'))),
    '2wRPGbwBNxhShjRczx8GfS2c4cjvs4NJskeWloUNtp8='
  UNION ALL
  SELECT 'eszett',
    `example-gcp-project.drop_hash_index.normalize_name`('Straße'),
    'strasse',
    NULL,
    NULL
),
ndz AS (
  SELECT
    TO_BASE64(SHA256(
      TO_BASE64(SHA256(`example-gcp-project.drop_hash_index.normalize_name`('Danielle')))
      || TO_BASE64(SHA256(`example-gcp-project.drop_hash_index.normalize_name`('Johnson')))
      || TO_BASE64(SHA256('19850704'))
      || TO_BASE64(SHA256('91790'))
    )) AS got_ndz,
    'PQOfn1RffEKmqMmNAzDKKaoZCwxWbQZkQzPWmQo9REA=' AS want_ndz
)
SELECT case_id, got_std, want_std, got_hash, want_hash
FROM cases
WHERE got_std IS DISTINCT FROM want_std
   OR (want_hash IS NOT NULL AND got_hash IS DISTINCT FROM want_hash)
UNION ALL
SELECT 'ndz_danielle', got_ndz, want_ndz, NULL, NULL
FROM ndz
WHERE got_ndz IS DISTINCT FROM want_ndz;
