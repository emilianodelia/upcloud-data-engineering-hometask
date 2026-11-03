-- One row per daily file the runner has checked: did it exist, was it loaded, how many rows came in.
-- Days never checked are not here: make reconcile probes every day and adds them.
with rows_per_day as (
    select
        billed_at,
        count(*) as rows_loaded
    from {{ ref('fct_resource_usage_invoices') }}
    group by billed_at
)

select
    manifest.file_date,
    case manifest.status
        when 200 then 'found'
        when 404 then 'missing'
        else 'error'
    end as file_status,
    manifest.loaded_etag is not null as is_loaded,
    -- the file changed in the bucket after we loaded it
    case when manifest.loaded_etag <> manifest.etag then true else false end as is_stale,
    manifest.loaded_at,
    -- 0 when nothing was loaded for that day
    coalesce(rows_per_day.rows_loaded, 0) as rows_loaded
from {{ source('ops_ingestion', 'billing_file_manifest') }} as manifest
left join rows_per_day
    on rows_per_day.billed_at = manifest.file_date
