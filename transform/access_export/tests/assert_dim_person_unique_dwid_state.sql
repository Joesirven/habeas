-- Person mart must be unique on (dwid, state); duplicate spine rows would
-- duplicate every table slice in a requester's access pack.
select
    dwid,
    state,
    count(*) as row_count
from {{ ref('dim_person') }}
group by dwid, state
having count(*) > 1
