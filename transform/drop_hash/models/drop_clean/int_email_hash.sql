with source as (
    select
        dwid,
        state,
        emailaddress
    from {{ ref('stg_person') }}

    union all

    select
        dwid,
        state,
        emailaddress
    from {{ ref('stg_emails_digital_only') }}
),

standardized as (
    select
        dwid,
        state,
        nullif(lower(regexp_replace(emailaddress, r'\s', '')), '') as email_std
    from source
)

-- Grain: one row per (dwid, state, email_std) across MDR person + digital source.
select distinct
    dwid,
    state,
    email_std,
    case
        when email_std is not null then to_base64(sha256(email_std))
    end as email_hash
from standardized
