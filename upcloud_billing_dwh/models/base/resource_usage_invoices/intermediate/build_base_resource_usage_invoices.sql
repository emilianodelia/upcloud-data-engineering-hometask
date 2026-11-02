{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='partition_date'
) }}

{% set window = billing_window() %}

with source as (

    select *
    from read_csv(
        {{ billing_urls(window.start_date, window.end_date) }},
        hive_partitioning = true,
        filename = true,
        all_varchar = true
    )
),

scope as (
    select 
        cast(invoice_id as string) as invoice_id,
        timestamp, 
        cast(resource_id as string) as resource_id, 
        -- GDPR: user_id is personal data, pseudonymised with a salted hash (counts and joins still work)
        -- shortcut: the salt shows up in compiled SQL under target/; in production read it from a secret store
        sha256('{{ env_var("BILLING_PII_SALT", "local-dev-salt") }}' || user_id) as user_id,
        cast(operation_type as string) as operation_type, 
        cast(currency as string) as currency, 
        round(cast(credit_usage as numeric), 2) as credit_usage, 
        cast(service_tier as string) as service_tier, 
        cast(success as boolean) as is_successful, 
        cast(resource_type as string) as resource_type,
        cast(region as string) as region_code, 
        upper(split_part(region, '-', 1)) as country_code, 
        upper(left(split_part(region, '-', 2), 3)) as city_code, 
        cast(regexp_extract(region, '(\d+)$', 1) as string) as site_number, 
        make_date(year::int, month::int, day::int) as partition_date,
        -- lineage: which file and which dbt run each row came from
        filename as source_file,
        '{{ invocation_id }}' as dbt_invocation_id
    from source
)

select * from scope