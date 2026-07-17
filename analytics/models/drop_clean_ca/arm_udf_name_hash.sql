{{ config(materialized='table', tags=['drop_clean_ca', 'arm_udf']) }}

-- Name hashes via persistent JS UDF.
-- Timeout / slot pressure: chunk by dwid ranges — see analytics/udf/README.md

with normalized as (
    select
        p.dwid,
        p.state,
        `example-gcp-project.drop_hash_experiment.normalize_name`(p.firstname) as first_name_std,
        `example-gcp-project.drop_hash_experiment.normalize_name`(p.lastname) as last_name_std
    from {{ ref('stg_ca_person') }} as p
)

select
    dwid,
    state,
    first_name_std,
    last_name_std,
    case
        when first_name_std is not null then to_base64(sha256(first_name_std))
    end as first_name_hash,
    case
        when last_name_std is not null then to_base64(sha256(last_name_std))
    end as last_name_hash
from normalized
