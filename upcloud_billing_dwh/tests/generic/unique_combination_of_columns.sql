-- fails on any combination of the given columns that appears more than once (the model's grain);
-- local replacement for dbt_utils.unique_combination_of_columns so the project needs no packages
{% test unique_combination_of_columns(model, combination_of_columns) %}

select
    {{ combination_of_columns | join(', ') }},
    count(*) as n_rows
from {{ model }}
group by {{ combination_of_columns | join(', ') }}
having count(*) > 1

{% endtest %}
