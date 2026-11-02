{% macro billing_urls(start_date, end_date) %}
    {%- set available = var('billing_available_dates', none) -%}
    {%- if available is not none -%}
        {%- if available | length == 0 -%}
            {{ exceptions.raise_compiler_error("billing_available_dates is empty — no files found in the requested window.") }}
        {%- endif -%}
        {%- set urls = [] -%}
        {%- for iso in available -%}
            {%- set d = modules.datetime.date.fromisoformat(iso) -%}
            {%- do urls.append(
                "'" ~ var('billing_base_url')
                ~ '/year=' ~ d.strftime('%Y')
                ~ '/month=' ~ d.strftime('%m')
                ~ '/day=' ~ d.strftime('%d')
                ~ '/billing.csv' ~ "'"
            ) -%}
        {%- endfor -%}
        [{{ urls | join(', ') }}]
    {%- else -%}
        {%- set start = modules.datetime.date.fromisoformat(start_date) -%}
        {%- set end = modules.datetime.date.fromisoformat(end_date) -%}
        {%- set n_days = (end - start).days -%}
        [
        {%- for i in range(n_days + 1) -%}
            {%- set d = start + modules.datetime.timedelta(days=i) -%}
            '{{ var("billing_base_url") }}/year={{ d.strftime("%Y") }}/month={{ d.strftime("%m") }}/day={{ d.strftime("%d") }}/billing.csv'
            {{- "," if not loop.last -}}
        {%- endfor -%}
        ]
    {%- endif -%}
{% endmacro %}