{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='billed_at'
) }}

{% set window = billing_window() %}

with invoices as (
    select *
    from {{ ref('base_resource_usage_invoices') }}
    {% if is_incremental() %}
    -- only the run's window: delete+insert replaces exactly these days
    -- shortcut: a reconcile of scattered days reprocesses everything between min and max (from base, no download)
    where partition_date between '{{ window.start_date }}' and '{{ window.end_date }}'
    {% endif %}
),

final as (
    select

        -- identifiers and grain definition
        invoices.user_id,
        invoices.invoice_id,

        -- when
        invoices.partition_date as billed_at,

        -- where
        -- city name can be left out given that there is only one city per country
        -- If more cities get added as time goes by we can add that granularity
        -- by just adding the column here
        dim_location.country_name as country,

        -- what / usage specs
        invoices.resource_type,
        invoices.service_tier,
        invoices.operation_type,
        invoices.is_successful,

        -- who pays 
        -- the client's billing currency, for reference only
        invoices.currency as billing_currency,

        -- how much: credits are stored negative for consumption, flip the sign once here
        -- so every mart reads consumption as positive
        -1 * invoices.credit_usage as credits_consumed,

        -- business rule, defined only here: a transaction's credits are charged when it
        -- succeeded, and uncharged when it failed. Every report sums these two columns.
        case when invoices.is_successful then -1 * invoices.credit_usage else 0 end as credits_charged,
        case when not invoices.is_successful then -1 * invoices.credit_usage else 0 end as credits_uncharged

    from invoices
    left join {{ ref('dim_location') }}
        on invoices.region_code = dim_location.region_code
)

select * from final
