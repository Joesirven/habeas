{{ config(cluster_by=['state', 'dwid']) }}

-- Multi-row per dwid by design (ballot grain).
select
    s.*,
    current_timestamp() as dbt_updated_at
from {{ ref('stg_ballots') }} as s
