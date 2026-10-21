-- One row per complaint: typed canonical columns plus analysis flags.
with source as (
    select * from {{ source('lake', 'complaints_archive') }}
),

bureaus as (
    select company from {{ ref('bureau_companies') }}
)

select
    s.complaint_id,
    s.date_received,
    s.date_sent_to_company,
    s.product,
    s.sub_product,
    s.issue,
    s.sub_issue,
    s.company,
    case when b.company is not null then 'bureau' else 'other' end as segment,
    s.state,
    s.zip_code,
    s.tags,
    s.submitted_via,
    s.company_public_response,
    s.company_response,
    s.timely_response = 'Yes' as is_timely,
    case
        when s.company_response is null or s.company_response = 'In progress' then null
        when s.company_response in (
            'Closed with monetary relief', 'Closed with non-monetary relief', 'Closed with relief'
        ) then true
        else false
    end as relief_given,
    s.narrative,
    s.narrative is not null as has_narrative,
    md5(s.narrative) as narrative_hash,
    s.row_hash,
    s.source_file
from source as s
left join bureaus as b on s.company = b.company
