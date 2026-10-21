-- Narratives whose exact text appears more than once: candidates for template / campaign filings.
select
    narrative_hash,
    count(*) as n_copies,
    count(distinct company) as n_companies,
    min(date_received) as first_seen,
    max(date_received) as last_seen
from {{ ref('stg_complaints') }}
where narrative_hash is not null
group by narrative_hash
having count(*) >= 2
