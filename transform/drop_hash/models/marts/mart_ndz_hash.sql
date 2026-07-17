{{ config(
    alias='ndz_hash__build',
    tags=['mart', 'serving_staging']
) }}

select distinct
    ndz_hash as hash,
    dwid,
    state
from {{ ref('int_ndz_hash') }}
where ndz_hash is not null
