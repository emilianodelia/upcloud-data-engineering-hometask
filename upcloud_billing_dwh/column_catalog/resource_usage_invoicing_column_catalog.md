# Column documentation

Every documented column of the final models. Reference them in yml with
`description: "{{ doc('<block_name>') }}"` instead of copying the text.

## Identifiers

{% docs col_invoice_id %}
Identifier of the billing transaction. One row per invoice_id at transaction grain.
{% enddocs %}

{% docs col_resource_id %}
Identifier of the cloud resource the event refers to.
{% enddocs %}

{% docs col_user_id %}
Pseudonymised identifier of the user/account that owns the resource: sha256 of a secret salt
(env var BILLING_PII_SALT) and the source user_id. Stable across runs, so counts and joins work,
but the raw id is never stored in the warehouse.
{% enddocs %}

## Time

{% docs col_billing_date %}
Billing day (date), built from the source file's Hive year/month/day partition keys.
{% enddocs %}

{% docs col_timestamp %}
Event timestamp as delivered in the source file (raw string, not yet cast).
{% enddocs %}

## Location

{% docs col_region_code %}
Full region code as delivered in the source (renamed from region), for example fi-hel1.
Key to dim_location.
{% enddocs %}

{% docs col_country_code %}
ISO 3166-1 two-letter country code: the uppercased text before the first hyphen of the region code, for example FI.
{% enddocs %}

{% docs col_city_code %}
Three-letter city code: the uppercased first three letters of the location part of the region code, for example HEL.
{% enddocs %}

{% docs col_site_number %}
Trailing digits of the region code identifying the site within the city, as a string (for example '2' for fi-hel2).
{% enddocs %}

{% docs col_city_name %}
City name from the city_code_mapping seed, for example Helsinki.
{% enddocs %}

{% docs col_country_name %}
Country name from the country_and_region_code_mapping seed, for example Finland.
{% enddocs %}

{% docs col_continent %}
UN continent-level region, for example Europe.
{% enddocs %}

{% docs col_sub_region %}
UN sub-region, for example Northern Europe.
{% enddocs %}

## Usage specs

{% docs col_resource_type %}
Product the event refers to: vm, db, container or function.
{% enddocs %}

{% docs col_service_tier %}
Service tier of the resource at the time of the event: free, basic, pro or enterprise.
{% enddocs %}

{% docs col_operation_type %}
Type of operation that generated the billing event: compute, storage, read or write.
{% enddocs %}

{% docs col_is_successful %}
Whether the operation succeeded. Failed operations still carry credits.
{% enddocs %}

## Amounts

{% docs col_currency %}
Billing currency of the client, as in the source (EUR, USD or JPY). Each client has exactly one.
Reference only: credit amounts are not in this currency (see col_credit_usage).
{% enddocs %}

{% docs col_billing_currency %}
The client's billing currency (EUR, USD or JPY), for reference: where and how the client is invoiced.
Each client has exactly one. Credits are never converted with it.
{% enddocs %}

{% docs col_credit_usage %}
Credits of the operation, as in the source (negative for consumption), rounded to 2 decimals.
Credits are a platform unit, not money: the distribution (0.01 to 100 per transaction) is the same
whatever the client's currency. What a credit costs depends on the client's agreed rate, not in the source.
{% enddocs %}

{% docs col_credits_consumed %}
Credits of the transaction with the sign flipped, so consumption is positive. Platform unit, not money.
{% enddocs %}

## Active users

{% docs col_billed_month %}
First day of the billing month (date), from billed_at truncated to the month.
{% enddocs %}

{% docs col_active_users %}
Distinct users with at least one billing transaction in the period, across all tiers.
{% enddocs %}

{% docs col_active_free_tier_users %}
Distinct users with at least one free tier transaction in the period.
{% enddocs %}

{% docs col_active_basic_tier_users %}
Distinct users with at least one basic tier transaction in the period.
{% enddocs %}

{% docs col_active_pro_tier_users %}
Distinct users with at least one pro tier transaction in the period.
{% enddocs %}

{% docs col_active_enterprise_tier_users %}
Distinct users with at least one enterprise tier transaction in the period.
{% enddocs %}

## Billing measures

{% docs col_total_transactions %}
Number of billing transactions (invoice_id), successful or not. Additive.
{% enddocs %}

{% docs col_successful_transactions %}
Number of successful billing transactions. Additive.
{% enddocs %}

{% docs col_failed_transactions %}
Number of failed billing transactions. Additive.
{% enddocs %}

## Credit usage reports

{% docs col_failure_rate %}
failed_transactions / total_transactions, as a fraction (0.05 = 5%).
{% enddocs %}

{% docs col_avg_credits_per_transaction %}
credits_charged / successful_transactions: what a charged transaction costs on average.
{% enddocs %}

{% docs col_days_loaded %}
Number of days of the period with data loaded.
{% enddocs %}

{% docs col_is_partial %}
True when fewer days are loaded than the period has (the period is still running, or a day is missing).
A partial period is not comparable with a full one.
{% enddocs %}

{% docs col_avg_daily_credits_charged %}
credits_charged / days_loaded, so a partial period compares with a full one.
{% enddocs %}

{% docs col_avg_daily_credits_uncharged %}
credits_uncharged / days_loaded.
{% enddocs %}

{% docs col_report_dimension %}
'All' on the rows that total every value of this column (see the model description).
{% enddocs %}

{% docs col_credits_charged %}
Credits of successful transactions, consumption positive (0 for a failed one). Additive.
The rule is defined once, in fct_resource_usage_invoices. Platform unit, not money.
{% enddocs %}

{% docs col_credits_uncharged %}
Credits of failed transactions: consumed but not charged, consumption positive (0 for a successful
one). Additive. Not included in credits_charged. Defined once, in fct_resource_usage_invoices.
{% enddocs %}

## Lineage

{% docs col_source_file %}
URL of the daily source file the row was read from.
{% enddocs %}

{% docs col_dbt_invocation_id %}
dbt invocation_id of the run that loaded the row; matches the run's logs and target/run_results.json.
{% enddocs %}
