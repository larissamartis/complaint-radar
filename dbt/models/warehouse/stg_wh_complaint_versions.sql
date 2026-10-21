-- Every loaded version of every complaint in the 60-day hot window.
select
    complaint_id,
    date_received,
    date_sent_to_company,
    product,
    sub_product,
    issue,
    sub_issue,
    company,
    state,
    tags,
    submitted_via,
    company_response,
    timely_response = 'Yes' as is_timely,
    row_hash,
    loaded_date,
    run_id
from {{ source('warehouse', 'raw_complaint_versions') }}
