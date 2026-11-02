with data_centers as (
    select * from {{ ref('data_center_mapping') }}
),

cities as (
    select * from {{ ref('city_code_mapping') }}
),

countries as (
    select * from {{ ref('country_and_region_code_mapping') }}
),

final as (
    select
        data_centers.region_code,
        data_centers.site_number,
        data_centers.city_code,
        cities.city_name,
        cities.country_code,
        countries.full_name as country_name,
        countries.region as continent,
        countries.sub_region
    from data_centers
    left join cities
        on data_centers.city_code = cities.city_code
    left join countries
        on cities.country_code = countries.alpha_2
)

select * from final
