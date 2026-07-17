{{ config(
    alias='phone_hash__build',
    tags=['mart', 'serving_staging'],
    cluster_by=['state', 'hash_value']
) }}

-- Cell and land are separate rows when both exist (stg_phones explode).
select distinct
    phone_hash as hash_value,
    cast(dwid as string) as dwid,
    state,
    current_timestamp() as built_at
from {{ ref('int_phone_hash') }}
where phone_hash is not null
