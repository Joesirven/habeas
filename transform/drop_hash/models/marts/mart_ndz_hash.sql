{{ config(
    alias='ndz_hash__build',
    tags=['mart', 'serving_staging'],
    cluster_by=['state', 'hash_value']
) }}

select distinct
    ndz_hash as hash_value,
    cast(dwid as string) as dwid,
    state,
    current_timestamp() as built_at
from {{ ref('int_ndz_hash') }}
where ndz_hash is not null
