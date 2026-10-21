-- Daily counts over the hot window, same grain as the local fct_complaints_daily.
select
    date_received,
    segment,
    company,
    product,
    coalesce(issue, '(none)') as issue,
    count(*) as n_complaints,
    countif(relief_given) as n_relief,
    countif(company_response = 'Untimely response') as n_untimely,
    countif(company_response = 'In progress') as n_in_progress
from {{ ref('wh_complaints_current') }}
group by 1, 2, 3, 4, 5
