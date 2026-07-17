-- CPPA v1.2.0 phone vector: +1(415)555-9317
with vectors as (
    select '+1(415)555-9317' as raw_input
),

digits as (
    select regexp_replace(raw_input, r'[^0-9]', '') as phone_digits
    from vectors
),

computed as (
    select
        case
            when length(phone_digits) >= 10 then right(phone_digits, 10)
            else phone_digits
        end as phone_std,
        to_base64(sha256(
            case
                when length(phone_digits) >= 10 then right(phone_digits, 10)
                else phone_digits
            end
        )) as phone_hash
    from digits
)

select *
from computed
where phone_std != '4155559317'
    or phone_hash != 'vGM7y5n+hBXRSEAklhHDPCbysyNgYTmXdMcagGUOY8E='
