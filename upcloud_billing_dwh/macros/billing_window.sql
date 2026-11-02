{#
    The billing window of the current run: the days every incremental billing model (re)processes.

    Default: ends the day before exec_date and starts billing_lookback_days earlier.
    Override: billing_start_date / billing_end_date vars (backfills, run_pipeline.py).

    Usage:
        {% set window = billing_window() %}
        {{ window.start_date }}  ->  '2025-12-15'
        {{ window.end_date }}    ->  '2025-12-17'
#}
{% macro billing_window() %}
    {%- set exec_date = modules.datetime.date.fromisoformat(
        var('exec_date', run_started_at.strftime('%Y-%m-%d'))
    ) -%}
    {%- set default_end = exec_date - modules.datetime.timedelta(days=1) -%}
    {%- set default_start = default_end - modules.datetime.timedelta(days=var('billing_lookback_days')) -%}

    {{ return({
        'start_date': var('billing_start_date', default_start.strftime('%Y-%m-%d')),
        'end_date': var('billing_end_date', default_end.strftime('%Y-%m-%d'))
    }) }}
{% endmacro %}
