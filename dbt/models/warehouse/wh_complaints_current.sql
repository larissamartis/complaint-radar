-- Current state of each complaint = its most recently loaded version.
-- Replaces an UPDATE/MERGE, which the BigQuery sandbox does not allow.
with versions as (
    select * from {{ ref('stg_wh_complaint_versions') }}
),

bureaus as (
    select company from {{ ref('bureau_companies') }}
)

select
    v.* except (row_hash, run_id),
    case when b.company is not null then 'bureau' else 'other' end as segment,
    case
        when v.company_response is null or v.company_response in ('In progress', 'Untimely response') then null
        when v.company_response in (
            'Closed with monetary relief', 'Closed with non-monetary relief', 'Closed with relief'
        ) then true
        else false
    end as relief_given
from versions as v
left join bureaus as b on v.company = b.company
qualify row_number() over (partition by v.complaint_id order by v.loaded_date desc, v.run_id desc) = 1
