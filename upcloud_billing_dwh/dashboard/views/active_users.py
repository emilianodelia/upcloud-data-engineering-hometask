import streamlit as st

from common import bars_with_trend, load_active_users, load_daily_active_users, pct_delta

st.title("Active users")
st.caption("A user is active in a month with at least one billing transaction, successful or not. "
           "Not affected by the sidebar filters: distinct counts don't add up across slices.")

df = load_active_users()
latest = df.iloc[-1]
partial = f" (through {latest.data_through:%d %b})" if latest.is_partial_month else ""

c1, c2 = st.columns(2)
c1.metric(f"Active users, {latest.billed_year_month:%b %Y}{partial}", f"{int(latest.total_active_users):,}",
          pct_delta(latest.total_active_users, latest.prior_month_same_period_active_users), border=True)
c2.metric("Months loaded", len(df), border=True)

daily = load_daily_active_users()
st.subheader("Active users per day")
st.caption("Bars: distinct users with a transaction that day. Line: 7-day trailing average.")
st.altair_chart(bars_with_trend(daily, "billed_at", "active_users", y_title="Active users", y_format=",d"),
                width="stretch")

tier_cols = ["total_active_free_tier_users", "total_active_basic_tier_users",
             "total_active_pro_tier_users", "total_active_enterprise_tier_users"]
if (df[tier_cols].eq(df["total_active_users"], axis=0)).all().all():
    st.warning("Every user is active in every tier, so the tier columns equal the total. "
               "In this data the tier is set per transaction, not per user.")

st.subheader("Per month")
st.dataframe(df, hide_index=True, width="stretch",
             column_config={"billed_year_month": st.column_config.DateColumn("Month", format="MMM YYYY"),
                            "data_through": st.column_config.DateColumn("Data through", format="DD MMM YYYY")})
