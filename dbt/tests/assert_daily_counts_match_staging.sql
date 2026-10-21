-- Fails if the daily mart loses or duplicates complaints.
select *
from (select sum(n_complaints) as mart_total from {{ ref('fct_complaints_daily') }})
cross join (select count(*) as staging_total from {{ ref('stg_complaints') }})
where mart_total != staging_total
