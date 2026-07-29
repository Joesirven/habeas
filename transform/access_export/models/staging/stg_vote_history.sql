select *
from {{ source('person_db', 'vote_history') }}
