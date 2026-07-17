with source as (
    select
        dwid,
        state,
        regaddrzip
    from {{ ref('stg_ca_person') }}
),

zip_part as (
    select
        dwid,
        state,
        split(regaddrzip, '-')[safe_offset(0)] as zip_base
    from source
),

standardized as (
    select
        dwid,
        state,
        nullif(
            substr(
                regexp_replace(
                    lower(regexp_replace(zip_base, r'[^a-zA-Z0-9]', '')),
                    r'^0+',
                    ''
                ),
                1,
                5
            ),
            ''
        ) as zip_std
    from zip_part
)

select
    dwid,
    state,
    zip_std,
    case
        when zip_std is not null then to_base64(sha256(zip_std))
    end as zip_hash
from standardized
