{{ config(
    alias='auth0_email_hash__build',
    tags=['mart', 'serving_staging', 'system_auth0'],
    cluster_by=['system', 'hash_value']
) }}

select distinct
    email_hash as hash_value,
    vendor_record_id,
    system,
    current_timestamp() as built_at
from {{ ref('stg_auth0_hashed') }}
where email_hash is not null
