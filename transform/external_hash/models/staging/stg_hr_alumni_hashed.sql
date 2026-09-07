{{ config(materialized='view') }}

-- Hashed raw only: dbt must never reference plaintext PII columns.
-- email_hash / phone_hash / ndz_hash are nullable (row may carry any subset).
select
    email_hash,
    phone_hash,
    ndz_hash,
    vendor_record_id,
    system,
    extracted_at
from {{ source('external_hash_index', 'hr_alumni_hashed_raw') }}
