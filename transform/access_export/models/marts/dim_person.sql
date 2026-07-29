{{ config(cluster_by=['state', 'dwid']) }}

-- dbt_updated_at is build provenance when materialized as table; for the
-- default view materialization it reflects query time.
select
    s.*,
    current_timestamp() as dbt_updated_at
from {{ ref('stg_person') }} as s
