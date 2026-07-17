with phones as (
    select
        dwid,
        state,
        phone_raw,
        phone_type
    from {{ ref('stg_phones') }}
),

digits as (
    select
        dwid,
        state,
        phone_type,
        regexp_replace(phone_raw, r'[^0-9]', '') as phone_digits
    from phones
),

standardized as (
    select
        dwid,
        state,
        phone_type,
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
    phone_type,
    phone_std,
    case
        when phone_std is not null then to_base64(sha256(phone_std))
    end as phone_hash
from standardized
