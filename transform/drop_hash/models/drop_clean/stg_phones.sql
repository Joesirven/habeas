{{ config(materialized='view') }}

-- One row per available phone type (cell and land are separate when both exist).
with source as (
    select
        dwid,
        state,
        nullif(trim(likely_cell_phone), '') as cell_phone,
        nullif(trim(likely_land_phone), '') as land_phone
    from {{ source('person_db', 'phones') }}
    where state = '{{ var("state") }}'
)

select dwid, state, cell_phone as phone_raw, 'cell' as phone_type
from source
where cell_phone is not null

union all

select dwid, state, land_phone as phone_raw, 'land' as phone_type
from source
where land_phone is not null
