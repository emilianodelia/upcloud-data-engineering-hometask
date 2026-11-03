-- One row per billing day, with charged and uncharged credits per country side by side.
-- A new country needs its two columns added here: the accepted_values test on the fact's
-- country column stops the build until it is.
select
    billed_at,

    sum(credits_charged) filter (where country = 'Finland') as finland_credits_charged,
    sum(credits_uncharged) filter (where country = 'Finland') as finland_credits_uncharged,

    sum(credits_charged) filter (where country = 'Germany') as germany_credits_charged,
    sum(credits_uncharged) filter (where country = 'Germany') as germany_credits_uncharged,

    sum(credits_charged) filter (where country = 'Japan') as japan_credits_charged,
    sum(credits_uncharged) filter (where country = 'Japan') as japan_credits_uncharged,

    sum(credits_charged) filter (where country = 'Poland') as poland_credits_charged,
    sum(credits_uncharged) filter (where country = 'Poland') as poland_credits_uncharged,

    sum(credits_charged) filter (where country = 'United States of America') as usa_credits_charged,
    sum(credits_uncharged) filter (where country = 'United States of America') as usa_credits_uncharged
from {{ ref('fct_resource_usage_invoices') }}
group by billed_at
