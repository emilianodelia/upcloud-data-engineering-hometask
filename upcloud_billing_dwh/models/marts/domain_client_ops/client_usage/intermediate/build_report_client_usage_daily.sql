{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='billed_at'
) }}

{% set window = billing_window() %}

with client_transactions as (
    select
        billed_at,
        user_id,
        billing_currency,
        service_tier,
        is_successful,
        credits_consumed
    from {{ ref('fct_resource_usage_invoices') }}
    {% if is_incremental() %}
    -- only the run's window: each day aggregates from that day's rows alone
    where billed_at between '{{ window.start_date }}' and '{{ window.end_date }}'
    {% endif %}
),

daily_client_usage as (
    select
        billed_at,
        user_id,
        -- one billing currency per client, so it doesn't change the grain: kept to split clients by it
        billing_currency,
        service_tier,

        -- volumes
        count(*) as total_transactions,
        count(*) filter (where is_successful) as successful_transactions,
        count(*) filter (where not is_successful) as failed_transactions,

        -- same rule as report_billing_daily: credits charged count successful transactions only
        coalesce(sum(credits_consumed) filter (where is_successful), 0) as credits_charged,
        coalesce(sum(credits_consumed) filter (where not is_successful), 0) as credits_failed

    from client_transactions
    group by
        billed_at,
        user_id,
        billing_currency,
        service_tier
)

select * from daily_client_usage
