-- One row per billing day and per combination of country, resource type, service tier and
-- operation type, plus the 'All' total rows.
with daily as (
    select
        billed_at,
        -- group by cube(...) below also adds total rows, where a dimension is NULL for "all its values":
        -- coalesce writes 'All' instead of NULL, so the dashboard filters with country = 'All'
        coalesce(country, 'All') as country,
        coalesce(resource_type, 'All') as resource_type,
        coalesce(service_tier, 'All') as service_tier,
        coalesce(operation_type, 'All') as operation_type,
        sum(credits_charged) as credits_charged,
        sum(credits_uncharged) as credits_uncharged,
        count(*) as total_transactions,
        count(*) filter (where is_successful) as successful_transactions,
        count(*) filter (where not is_successful) as failed_transactions,
        count(*) filter (where not is_successful) / count(*) as failure_rate,
        sum(credits_charged) / count(*) filter (where is_successful) as avg_credits_per_transaction
    from {{ ref('fct_resource_usage_invoices') }}
    group by billed_at, cube(country, resource_type, service_tier, operation_type)
)

select
    *,
    -- average of the days loaded in the last 7 days, for the same slice
    avg(credits_charged) over (
        partition by country, resource_type, service_tier, operation_type
        order by billed_at
        range between interval 6 days preceding and current row
    ) as credits_charged_7d_avg
from daily
