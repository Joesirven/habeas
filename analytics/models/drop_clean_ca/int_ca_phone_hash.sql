with persons as (
    select
        dwid,
        state
    from {{ ref('stg_ca_person') }}
),

phones as (
    select
        dwid,
        state,
        phone_raw
    from {{ ref('stg_ca_phones') }}
),

joined as (
    select
        p.dwid,
        p.state,
        ph.phone_raw
    from persons as p
    left join phones as ph
        on p.dwid = ph.dwid
        and p.state = ph.state
),

digits as (
    select
        dwid,
        state,
        regexp_replace(phone_raw, r'[^0-9]', '') as phone_digits
    from joined
),

standardized as (
    select
        dwid,
        state,
        case
            when length(phone_digits) = 0 then null
            when length(phone_digits) >= 10 then right(phone_digits, 10)
            else phone_digits
        end as phone_std
    from digits
)

select
    dwid,
    state,
    phone_std,
    case
        when phone_std is not null then to_base64(sha256(phone_std))
    end as phone_hash
from standardized
