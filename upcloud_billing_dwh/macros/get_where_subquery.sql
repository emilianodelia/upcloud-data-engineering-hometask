{#
    Overrides dbt's get_where_subquery so test `where` configs can be scoped to the
    billing window of the current run (see macros/billing_window.sql).

    yml configs can't call custom macros, so tests use a placeholder that is replaced
    here at compile time:

        config:
          where: "partition_date __in_billing_window__"

    renders as: partition_date between '<window start>' and '<window end>'

    The window follows exec_date by default, or billing_start_date / billing_end_date
    on backfills, so tests check exactly the partitions the run just (re)loaded.
#}
{% macro get_where_subquery(relation) -%}
    {%- set where = config.get('where', '') -%}
    {%- if where -%}
        {%- if '__in_billing_window__' in where -%}
            {%- set window = billing_window() -%}
            {%- set where = where | replace(
                '__in_billing_window__',
                "between '" ~ window.start_date ~ "' and '" ~ window.end_date ~ "'"
            ) -%}
        {%- endif -%}
        {%- set filtered -%}
            (select * from {{ relation }} where {{ where }}) dbt_subquery
        {%- endset -%}
        {%- do return(filtered) -%}
    {%- else -%}
        {%- do return(relation) -%}
    {%- endif -%}
{%- endmacro %}
