-- One row per billing day: distinct users with at least one transaction that day, successful or not.
-- Not split by dimension: distinct users don't add up across slices.
select
    billed_at,
    count(distinct user_id) as active_users
from {{ ref('fct_resource_usage_invoices') }}
group by billed_at
