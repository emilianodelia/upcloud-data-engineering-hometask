{#
    Models: the schema mirrors the folder path under models/, so the warehouse reads like the project.
    Keeps the first two folder levels, plus 'intermediate' for models in an intermediate/ folder,
    joined with '__':

        models/base/resource_usage_invoices/intermediate/...   ->  base__resource_usage_invoices__intermediate
        models/core/core_dimensional/geographical_mapping/...   ->  core__core_dimensional
        models/marts/domain_finance/usage_invoice_reports/...   ->  marts__domain_finance

    Seeds follow the same rule under a 'seeds' layer (dbt leaves the seeds/ folder out of their fqn,
    so it is added back), keeping the two folder levels below it:

        seeds/geographical_mapping/...       ->  seeds__geographical_mapping
        seeds/utils/<topic>/...              ->  seeds__utils__<topic>

    A new folder (e.g. marts/domain_sales/) gets its schema with no config.
    An explicit +schema / config(schema=...) still wins, for one-off exceptions.
    Snapshots and anything else without a custom schema stay in the target schema (main).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is not none -%}
        {{ custom_schema_name | trim }}

    {%- elif node.resource_type == 'model' -%}
        {#- fqn = [project, folder, ..., model]: keep the folders only -#}
        {%- set folders = node.fqn[1:-1] -%}
        {%- set parts = folders[:2] -%}
        {%- if 'intermediate' in folders -%}
            {%- set parts = parts + ['intermediate'] -%}
        {%- endif -%}
        {{ parts | join('__') }}

    {%- elif node.resource_type == 'seed' -%}
        {#- fqn = [project, folder, ..., seed]: the seeds/ folder itself is not in it -#}
        {%- set folders = node.fqn[1:-1] -%}
        {{ (['seeds'] + folders[:2]) | join('__') }}

    {%- else -%}
        {{ target.schema }}
    {%- endif -%}
{%- endmacro %}
