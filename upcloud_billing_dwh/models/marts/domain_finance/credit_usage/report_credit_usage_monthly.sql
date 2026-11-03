-- One row per billing month and per combination of country, resource type, service tier and
-- operation type, plus the 'All' total rows. Same query as the daily report, by month.
select
    date_trunc('month', billed_at)::date as billed_month,
    -- group by cube(...) below also adds total rows, where a dimension is NULL for "all its values":
    -- coalesce writes 'All' instead of NULL, so the dashboard filters with country = 'All'
    coalesce(country, 'All') as country,
    coalesce(resource_type, 'All') as resource_type,
    coalesce(service_tier, 'All') as service_tier,
    coalesce(operation_type, 'All') as operation_type,
    count(distinct billed_at) as days_loaded,
    -- partial: fewer days loaded than the month has (still running, or a day is missing)
    count(distinct billed_at) < date_diff('day', billed_month, billed_month + interval 1 month) as is_partial,
    sum(credits_charged) as credits_charged,
    sum(credits_uncharged) as credits_uncharged,
    count(*) as total_transactions,
    count(*) filter (where is_successful) as successful_transactions,
    count(*) filter (where not is_successful) as failed_transactions,
    count(*) filter (where not is_successful) / count(*) as failure_rate,
    sum(credits_charged) / count(*) filter (where is_successful) as avg_credits_per_transaction,
    sum(credits_charged) / count(distinct billed_at) as avg_daily_credits_charged,
    sum(credits_uncharged) / count(distinct billed_at) as avg_daily_credits_uncharged
from {{ ref('fct_resource_usage_invoices') }}
group by billed_month, cube(country, resource_type, service_tier, operation_type)
