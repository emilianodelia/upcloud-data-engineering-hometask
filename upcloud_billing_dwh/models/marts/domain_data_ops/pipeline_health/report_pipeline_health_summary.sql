-- One row: the pipeline's headline numbers, for the dashboard tiles. Counted from the file manifest.
select
    max(file_date) filter (where loaded_etag is not null) as last_day_loaded,
    count(*) filter (where loaded_etag is not null) as files_loaded,
    count(*) filter (where status = 404) as files_missing,
    count(*) filter (where loaded_etag <> etag) as files_changed_since_loaded
from {{ source('ops_ingestion', 'billing_file_manifest') }}
