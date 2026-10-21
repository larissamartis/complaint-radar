-- Daily complaint counts at the grain used by emerging-issue detection.
select
    date_received,
    segment,
    company,
    product,
    coalesce(issue, '(none)') as issue,
    count(*) as n_complaints,
    count(*) filter (where has_narrative) as n_with_narrative,
    count(*) filter (where relief_given) as n_relief,
    count(*) filter (where company_response = 'Untimely response') as n_untimely,
    count(*) filter (where company_response = 'In progress') as n_in_progress
from {{ ref('stg_complaints') }}
group by all
