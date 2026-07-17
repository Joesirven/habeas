with source as (
    select
        dwid,
        state,
        birthdate
    from {{ ref('stg_person') }}
),

parsed as (
    select
        dwid,
        state,
        coalesce(
            safe.parse_date('%Y-%m-%d', birthdate),
            safe.parse_date('%m/%d/%Y', birthdate),
            safe.parse_date('%Y%m%d', birthdate),
            safe.parse_date('%m-%d-%Y', birthdate),
            safe.parse_date('%Y/%m/%d', birthdate),
            safe.parse_date('%B %e, %Y', birthdate),
            safe.parse_date('%b %e, %Y', birthdate),
            safe.parse_date('%B %d, %Y', birthdate),
            safe.parse_date('%b %d, %Y', birthdate)
        ) as birthdate_parsed
    from source
),

standardized as (
    select
        dwid,
        state,
        format_date('%Y%m%d', birthdate_parsed) as dob_std
    from parsed
)

select
    dwid,
    state,
    dob_std,
    case
        when dob_std is not null then to_base64(sha256(dob_std))
    end as dob_hash
from standardized
