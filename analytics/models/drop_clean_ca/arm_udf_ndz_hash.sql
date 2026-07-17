{{ config(materialized='table', tags=['drop_clean_ca', 'arm_udf']) }}

select
    n.dwid,
    n.state,
    case
        when n.first_name_hash is not null
         and n.last_name_hash is not null
         and d.dob_hash is not null
         and z.zip_hash is not null
        then to_base64(sha256(
            n.first_name_hash || n.last_name_hash || d.dob_hash || z.zip_hash
        ))
    end as ndz_hash
from {{ ref('arm_udf_name_hash') }} as n
inner join {{ ref('int_ca_dob_hash') }} as d
    using (dwid, state)
inner join {{ ref('int_ca_zip_hash') }} as z
    using (dwid, state)
