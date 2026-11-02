-- view: the build_ model is the one physical, incremental, tested table; a second
-- incremental copy could drift from it after a failed run (see PLANNING.md)
{{ config(materialized='view') }}

select *
from {{ ref('build_fct_resource_usage_invoices') }}
