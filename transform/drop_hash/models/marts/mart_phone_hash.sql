{{ config(
    alias='phone_hash__build',
    tags=['mart', 'serving_staging']
) }}

select distinct
    phone_hash as hash,
    dwid,
    state
from {{ ref('int_phone_hash') }}
where phone_hash is not null
