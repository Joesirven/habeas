-- CPPA v1.2.0 DOB vector: July 4, 1776
with vectors as (
    select 'July 4, 1776' as raw_input
),

parsed as (
    select
        coalesce(
            safe.parse_date('%Y-%m-%d', raw_input),
            safe.parse_date('%m/%d/%Y', raw_input),
            safe.parse_date('%Y%m%d', raw_input),
            safe.parse_date('%m-%d-%Y', raw_input),
            safe.parse_date('%Y/%m/%d', raw_input),
            safe.parse_date('%B %e, %Y', raw_input),
            safe.parse_date('%b %e, %Y', raw_input),
            safe.parse_date('%B %d, %Y', raw_input),
            safe.parse_date('%b %d, %Y', raw_input)
        ) as birthdate_parsed
    from vectors
),

computed as (
    select
        format_date('%Y%m%d', birthdate_parsed) as dob_std,
        to_base64(sha256(format_date('%Y%m%d', birthdate_parsed))) as dob_hash
    from parsed
)

select *
from computed
where dob_std != '17760704'
    or dob_hash != 'skXYXxBER6HQTZ3rXSZH1wVGLQ054mS5rbR/bwvzy4I='
