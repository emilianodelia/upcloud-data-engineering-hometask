import altair as alt
import streamlit as st

from common import BLUE, CLIENT_OPS, FINANCE, RED, count, credits, millions_axis, q, rate, slice_filters

TABLE = f"{FINANCE}.report_credit_usage_daily"

st.title("Credit usage, daily")
where, params = slice_filters(TABLE)
df = q(f"select * from {TABLE} where {where} order by billed_at", params)
latest = df.iloc[-1]
users = q(f"select active_users from {CLIENT_OPS}.report_active_users_daily where billed_at = ?",
          [latest.billed_at]).active_users
st.caption(f"Latest day loaded: **{latest.billed_at:%A %d %b %Y}**. Credits are a platform unit, not money.")

c = st.columns(4)
c[0].metric("Credits charged", credits(latest.credits_charged), border=True,
            help=f"Successful transactions. 7-day average: {credits(latest.credits_charged_7d_avg)}")
c[1].metric("Credits uncharged", credits(latest.credits_uncharged), border=True,
            help="Credits of failed transactions: consumed but not charged")
c[2].metric("Avg credits per transaction", f"{latest.avg_credits_per_transaction:,.2f} cr", border=True,
            help="Credits charged / successful transactions")
c[3].metric("Active users", count(users.iloc[0]) if len(users) else "–", border=True,
            help="All users with a transaction that day: not affected by the filters (distinct users don't add up)")
c = st.columns(4)
c[0].metric("Transactions", count(latest.total_transactions), border=True)
c[1].metric("Successful transactions", count(latest.successful_transactions), border=True)
c[2].metric("Failed transactions", count(latest.failed_transactions), border=True)
c[3].metric("Failure rate", rate(latest.failure_rate), border=True, help="Failed / all transactions")

st.subheader("Credits per day")
st.caption("Bars: charged (blue) and uncharged (red) credits. Line: 7-day average of charged credits.")
base = alt.Chart(df).encode(x=alt.X("yearmonthdate(billed_at):T", title=None, axis=alt.Axis(format="%d %b", grid=False)))
bars = base.transform_fold(["credits_charged", "credits_uncharged"], as_=["kind", "credits"]).mark_bar(width={"band": 0.8}).encode(
    y=alt.Y("credits:Q", axis=millions_axis("Credits")),
    color=alt.Color("kind:N", scale=alt.Scale(domain=["credits_charged", "credits_uncharged"], range=[BLUE, RED]),
                    legend=alt.Legend(title=None, orient="top", labelExpr="datum.label == 'credits_charged' ? 'Charged' : 'Uncharged'")),
    tooltip=[alt.Tooltip("billed_at:T", title="Day", format="%d %b %Y"), alt.Tooltip("kind:N", title="Credits"),
             alt.Tooltip("credits:Q", format=",.0f")])
line = base.mark_line(color="#52514e", strokeWidth=2).encode(y="credits_charged_7d_avg:Q", x=alt.X("yearmonthdate(billed_at):T", bandPosition=0.5))
st.altair_chart(alt.layer(bars, line).properties(height=320), width="stretch")

st.subheader("Usage by country")
st.caption("Charged credits per day, split by country. All tiers, resources and operations: the filters above don't apply here.")
by_country = q(f"select * from {FINANCE}.report_credit_usage_by_country_daily order by billed_at")
charged = [c for c in by_country.columns if c.endswith("_credits_charged")]
st.altair_chart(alt.Chart(by_country).transform_fold(charged, as_=["column", "credits"])
                .transform_calculate(key="replace(datum.column, '_credits_charged', '')")
                .transform_calculate(country="datum.key == 'usa' ? 'USA' : upper(slice(datum.key, 0, 1)) + slice(datum.key, 1)")
                .mark_bar(width={"band": 0.8}).encode(
                    x=alt.X("yearmonthdate(billed_at):T", title=None, axis=alt.Axis(format="%d %b", grid=False)),
                    y=alt.Y("credits:Q", axis=millions_axis("Credits charged")),
                    color=alt.Color("country:N", legend=alt.Legend(title=None, orient="top")),
                    tooltip=[alt.Tooltip("billed_at:T", title="Day", format="%d %b %Y"), alt.Tooltip("country:N"),
                             alt.Tooltip("credits:Q", title="Credits charged", format=",.0f")])
                .properties(height=320), width="stretch")
st.dataframe(by_country.iloc[::-1], hide_index=True, width="stretch",
             column_config={"billed_at": st.column_config.DateColumn("Day", format="DD MMM YYYY")}
             | {c: st.column_config.NumberColumn(c.replace("_", " ").capitalize(), format="%.0f")
                for c in by_country.columns if c != "billed_at"})

st.subheader("Per day")
st.dataframe(df.iloc[::-1], hide_index=True, width="stretch",
             column_order=["billed_at", "credits_charged", "credits_uncharged", "credits_charged_7d_avg",
                           "total_transactions", "successful_transactions", "failed_transactions",
                           "failure_rate", "avg_credits_per_transaction"],
             column_config={"billed_at": st.column_config.DateColumn("Day", format="DD MMM YYYY"),
                            "credits_charged": st.column_config.NumberColumn("Credits charged", format="%.0f"),
                            "credits_uncharged": st.column_config.NumberColumn("Credits uncharged", format="%.0f"),
                            "credits_charged_7d_avg": st.column_config.NumberColumn("7-day avg charged", format="%.0f"),
                            "total_transactions": st.column_config.NumberColumn("Transactions", format="%d"),
                            "successful_transactions": st.column_config.NumberColumn("Successful", format="%d"),
                            "failed_transactions": st.column_config.NumberColumn("Failed", format="%d"),
                            "failure_rate": st.column_config.NumberColumn("Failure rate", format="percent"),
                            "avg_credits_per_transaction": st.column_config.NumberColumn("Avg per transaction", format="%.2f")})
