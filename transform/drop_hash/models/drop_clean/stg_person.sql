{{ config(materialized='view') }}

select
    dwid,
    state,
    firstname,
    lastname,
    birthdate,
    regaddrzip,
    emailaddress
from {{ source('person_db', 'person') }}
where state = '{{ var("state") }}'
