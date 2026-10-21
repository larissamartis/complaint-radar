-- Fails if the daily mart has more than one row per grain.
select date_received, segment, company, product, issue, count(*) as n
from {{ ref('fct_complaints_daily') }}
group by all
having count(*) > 1
