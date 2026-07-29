select *
from {{ source('person_db', 'phones') }}
