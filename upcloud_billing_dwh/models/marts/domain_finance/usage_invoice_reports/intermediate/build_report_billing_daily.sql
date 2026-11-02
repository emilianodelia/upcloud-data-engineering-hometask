{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='billed_at'
) }}

{% set window = billing_window() %}

with billing_transactions as (
    select
        billed_at,
        country,
        resource_type,
        service_tier,
        operation_type,
        is_successful,
        credits_consumed
    from {{ ref('fct_resource_usage_invoices') }}
    {% if is_incremental() %}
    -- only the run's window: each day aggregates from that day's rows alone
    where billed_at between '{{ window.start_date }}' and '{{ window.end_date }}'
    {% endif %}
),

daily_billing_metrics as (
    select
        billed_at,
        country,
        resource_type,
        service_tier,
        operation_type,

        -- volumes
        count(*) as total_transactions,
        count(*) filter (where is_successful) as successful_transactions,
        count(*) filter (where not is_successful) as failed_transactions,

        -- credits charged count successful transactions only; failed credits are reported separately
        coalesce(sum(credits_consumed) filter (where is_successful), 0) as credits_charged,
        coalesce(sum(credits_consumed) filter (where not is_successful), 0) as credits_failed

    from billing_transactions
    group by
        billed_at,
        country,
        resource_type,
        service_tier,
        operation_type
)

select * from daily_billing_metrics
