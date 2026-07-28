-- Thin passthrough; no business logic (KTD-13 staging layer).
select *
from {{ source('person_db', 'person') }}
