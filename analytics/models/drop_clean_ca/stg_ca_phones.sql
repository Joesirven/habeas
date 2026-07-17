{{ config(materialized='view') }}

select
    dwid,
    state,
    coalesce(
        nullif(trim(likely_cell_phone), ''),
        nullif(trim(likely_land_phone), '')
    ) as phone_raw,
    likely_cell_phone,
    likely_land_phone
from {{ source('person_db', 'phones') }}
where state = 'CA'
