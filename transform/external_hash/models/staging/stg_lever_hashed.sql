{{ config(materialized='view', tags=['staging', 'system_lever']) }}

select
    email_hash,
    phone_hash,
    ndz_hash,
    vendor_record_id,
    system,
    extracted_at
from {{ source('external_hash_index', 'lever_hashed_raw') }}
where email_hash is not null
