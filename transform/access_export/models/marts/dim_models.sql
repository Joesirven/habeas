{{ config(cluster_by=['state', 'dwid']) }}

select
    s.*,
    current_timestamp() as dbt_updated_at
from {{ ref('stg_models') }} as s
