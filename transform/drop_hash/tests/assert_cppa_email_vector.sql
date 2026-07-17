-- CPPA v1.2.0 email vector: Anna.Smith@Domain.com
with vectors as (
    select 'Anna.Smith@Domain.com' as raw_input
),

computed as (
    select
        lower(regexp_replace(raw_input, r'\s', '')) as email_std,
        to_base64(sha256(lower(regexp_replace(raw_input, r'\s', '')))) as email_hash
    from vectors
)

select *
from computed
where email_std != 'anna.smith@domain.com'
    or email_hash != 'KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE='
