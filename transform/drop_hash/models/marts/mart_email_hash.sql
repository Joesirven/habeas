{{ config(
    alias='email_hash__build',
    tags=['mart', 'serving_staging']
) }}

select distinct
    email_hash as hash,
    dwid,
    state
from {{ ref('int_email_hash') }}
where email_hash is not null
