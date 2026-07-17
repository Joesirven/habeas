{{ config(
    alias='email_hash__build',
    tags=['mart', 'serving_staging'],
    cluster_by=['state', 'hash_value']
) }}

select distinct
    email_hash as hash_value,
    cast(dwid as string) as dwid,
    state,
    current_timestamp() as built_at
from {{ ref('int_email_hash') }}
where email_hash is not null
