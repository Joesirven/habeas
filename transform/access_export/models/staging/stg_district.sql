select *
from {{ source('person_db', 'district') }}
