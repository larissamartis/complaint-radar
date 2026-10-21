-- One row per company.
select
    company,
    any_value(segment) as segment,
    min(date_received) as first_seen,
    max(date_received) as last_seen,
    count(*) as n_complaints
from {{ ref('stg_complaints') }}
group by company
