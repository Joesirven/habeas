{{ config(materialized='view', tags=['staging', 'system_mailchimp']) }}

-- Hashed raw only: dbt must never reference plaintext PII columns.
select
    email_hash,
    phone_hash,
    ndz_hash,
    vendor_record_id,
    system,
    extracted_at
from {{ source('external_hash_index', 'mailchimp_hashed_raw') }}
where email_hash is not null
