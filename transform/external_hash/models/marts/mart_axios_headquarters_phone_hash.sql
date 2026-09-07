{{ config(
    alias='axios_headquarters_phone_hash__build',
    tags=['mart', 'serving_staging'],
    cluster_by=['system', 'hash_value']
) }}

select distinct
    phone_hash as hash_value,
    vendor_record_id,
    system,
    current_timestamp() as built_at
from {{ ref('stg_axios_headquarters_hashed') }}
where phone_hash is not null
  and system = 'axios_headquarters'
