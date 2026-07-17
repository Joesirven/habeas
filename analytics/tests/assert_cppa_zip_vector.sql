-- CPPA v1.2.0 ZIP vectors (91790-3771, M1B 1A1, 00300-9999)
with vectors as (
    select '91790-3771' as raw_input, '91790' as expected_std, '2FPZucR4x7U8KlM+SFAX4LPGhwNz/PIZUCSUdDh0o/s=' as expected_hash
    union all
    select 'M1B 1A1', 'm1b1a', 'n8L9q8mVeT6Xt9/EeUNiTukGDrkbPJ3DvOEx14uElxk='
    union all
    select '00300-9999', '300', 'mDvWFLta/s5as7YCP3EUfNe2vCMU+dJ690IlQcZVg4k='
),

zip_part as (
    select
        raw_input,
        expected_std,
        expected_hash,
        split(raw_input, '-')[safe_offset(0)] as zip_base
    from vectors
),

computed as (
    select
        raw_input,
        expected_std,
        expected_hash,
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
),

hashed as (
    select
        raw_input,
        expected_std,
        expected_hash,
        zip_std,
        to_base64(sha256(zip_std)) as zip_hash
    from computed
)

select *
from hashed
where zip_std != expected_std
    or zip_hash != expected_hash
