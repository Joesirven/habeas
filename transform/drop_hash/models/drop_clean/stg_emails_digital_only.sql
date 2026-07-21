{{ config(materialized='view') }}

-- Digital-only email supplement (production_datasets); same shape as person.emailaddress.
select
    dwid,
    state,
    email as emailaddress
from {{ source('production_datasets', 'emails_digital_only_24q2') }}
where state = '{{ var("state") }}'
