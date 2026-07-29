select *
from {{ source('person_db', 'models') }}
