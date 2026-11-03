import altair as alt
import streamlit as st

from common import BLUE, FINANCE, count, credits, millions_axis, q, rate, slice_filters

# grain -> (dbt model, its period column, label format)
GRAINS = {"Day": ("report_credit_usage_daily", "billed_at", "%d %b %Y"),
          "Month": ("report_credit_usage_monthly", "billed_month", "%b %Y"),
          "Year": ("report_credit_usage_yearly", "billed_year", "%Y")}

st.title("Credit usage, history")
grain = st.segmented_control("Period", list(GRAINS), default="Month", key="grain") or "Month"
table, period, fmt = GRAINS[grain]
where, params = slice_filters(f"{FINANCE}.{table}")
df = q(f"select * from {FINANCE}.{table} where {where} order by {period}", params)
partial = df["is_partial"] if "is_partial" in df else False
df["period_label"] = df[period].dt.strftime(fmt) + (partial.map({True: " (partial)", False: ""}) if grain != "Day" else "")
latest = df.iloc[-1]
st.caption(f"Everything loaded, by {grain.lower()}. The cards show the latest one: **{latest.period_label}**.")

c = st.columns(4)
c[0].metric("Credits charged", credits(latest.credits_charged), border=True)
c[1].metric("Credits uncharged", credits(latest.credits_uncharged), border=True, help="Failed transactions: not charged")
if grain == "Day":
    c[2].metric("Avg credits per transaction", f"{latest.avg_credits_per_transaction:,.2f} cr", border=True)
else:
    c[2].metric("Avg credits charged per day", credits(latest.avg_daily_credits_charged), border=True,
                help=f"Over the {latest.days_loaded} days loaded")
    c[3].metric("Avg credits uncharged per day", credits(latest.avg_daily_credits_uncharged), border=True)
c = st.columns(4)
c[0].metric("Transactions", count(latest.total_transactions), border=True)
c[1].metric("Successful transactions", count(latest.successful_transactions), border=True)
c[2].metric("Failed transactions", count(latest.failed_transactions), border=True)
c[3].metric("Failure rate", rate(latest.failure_rate), border=True, help="Failed / all transactions")

st.subheader(f"Credits charged per {grain.lower()}")
st.caption("A partial period (fewer days loaded than it has) is faded, so it isn't read as a drop.")
df["faded"] = partial if grain != "Day" else False
st.altair_chart(alt.Chart(df).mark_bar(color=BLUE, cornerRadiusEnd=3).encode(
    x=alt.X("period_label:N", title=None, sort=None, axis=alt.Axis(labelAngle=0 if grain != "Day" else -45)),
    y=alt.Y("credits_charged:Q", axis=millions_axis("Credits charged")),
    opacity=alt.condition("datum.faded", alt.value(0.4), alt.value(0.9)),
    tooltip=[alt.Tooltip("period_label:N", title="Period"),
             alt.Tooltip("credits_charged:Q", title="Credits charged", format=",.0f"),
             alt.Tooltip("credits_uncharged:Q", title="Credits uncharged", format=",.0f")],
).properties(height=320), width="stretch")

st.subheader(f"Per {grain.lower()}")
columns = ["period_label", "days_loaded", "credits_charged", "credits_uncharged", "avg_daily_credits_charged",
           "avg_daily_credits_uncharged", "total_transactions", "successful_transactions", "failed_transactions",
           "failure_rate", "avg_credits_per_transaction"]
st.dataframe(df.iloc[::-1], hide_index=True, width="stretch", column_order=[c for c in columns if c in df],
             column_config={"period_label": st.column_config.TextColumn(grain),
                            "days_loaded": st.column_config.NumberColumn("Days loaded"),
                            "credits_charged": st.column_config.NumberColumn("Credits charged", format="%.0f"),
                            "credits_uncharged": st.column_config.NumberColumn("Credits uncharged", format="%.0f"),
                            "avg_daily_credits_charged": st.column_config.NumberColumn("Avg charged per day", format="%.0f"),
                            "avg_daily_credits_uncharged": st.column_config.NumberColumn("Avg uncharged per day", format="%.0f"),
                            "total_transactions": st.column_config.NumberColumn("Transactions", format="%d"),
                            "successful_transactions": st.column_config.NumberColumn("Successful", format="%d"),
                            "failed_transactions": st.column_config.NumberColumn("Failed", format="%d"),
                            "failure_rate": st.column_config.NumberColumn("Failure rate", format="percent"),
                            "avg_credits_per_transaction": st.column_config.NumberColumn("Avg per transaction", format="%.2f")})
