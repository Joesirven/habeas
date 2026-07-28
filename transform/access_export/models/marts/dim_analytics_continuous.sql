{{ config(cluster_by=['state', 'dwid']) }}

-- Kept separate from dim_models until hub IAM lands; the plan's target
-- dim_models then absorbs analytics_* columns.
select
    s.*,
    current_timestamp() as dbt_updated_at
from {{ ref('stg_analytics_continuous') }} as s
