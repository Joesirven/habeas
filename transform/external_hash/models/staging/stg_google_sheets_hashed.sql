{{ config(materialized='view', tags=['staging', 'system_google_sheets']) }}

select
    email_hash,
    phone_hash,
    ndz_hash,
    vendor_record_id,
    system,
    extracted_at
from {{ source('external_hash_index', 'google_sheets_hashed_raw') }}
where email_hash is not null
