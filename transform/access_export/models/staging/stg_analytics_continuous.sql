select *
from {{ source('person_db', 'analytics_continuous') }}
