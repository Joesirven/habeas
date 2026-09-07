{{ config(
    alias='hr_alumni_ndz_hash__build',
    tags=['mart', 'serving_staging'],
    cluster_by=['system', 'hash_value']
) }}

select distinct
    ndz_hash as hash_value,
    vendor_record_id,
    system,
    current_timestamp() as built_at
from {{ ref('stg_hr_alumni_hashed') }}
where ndz_hash is not null
  and system = 'hr_alumni'
