{{ config(materialized='view') }}

-- Hashed raw only: dbt must never reference plaintext PII columns.
select
    email_hash,
    vendor_record_id,
    system,
    extracted_at
from {{ source('external_hash_index', 'auth0_hashed_raw') }}
where email_hash is not null
  and system = 'auth0'
