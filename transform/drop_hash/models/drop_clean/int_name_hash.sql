{{ config(tags=['name_hash']) }}

-- Name hashes via persistent JS UDF in drop_hash_index.
-- Timeout / slot pressure: chunk by dwid ranges — see udf/README.md

{% set udf_fqn = target.project ~ '.drop_hash_index.normalize_name' %}

with normalized as (
    select
        p.dwid,
        p.state,
        `{{ udf_fqn }}`(p.firstname) as first_name_std,
        `{{ udf_fqn }}`(p.lastname) as last_name_std
    from {{ ref('stg_person') }} as p
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
