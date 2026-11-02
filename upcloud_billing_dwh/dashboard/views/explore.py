import streamlit as st

from common import (DIMENSIONS, MEASURES, aggregate, by_period, daily, fmt_value, heatmap,
                    monthly_summary, outcome_multiples, ranking_chart, trend_multiples)

st.title("Explore")
st.caption("Pick what to measure and what to compare. Narrow it down from the sidebar: "
           "date slider, and click a country, tier, resource or operation to focus on it.")

df = daily()

# ---------- what to look at ----------
c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
measure = c1.segmented_control("Measure", list(MEASURES), default="Credits charged", key="x_measure") or "Credits charged"
label = c2.segmented_control("Compare by", list(DIMENSIONS), default="Country", key="x_dim") or "Country"
m, dim = MEASURES[measure], DIMENSIONS[label]
col = m["col"]

by_dim = aggregate(df, [dim])
overall = aggregate(df, [])[col].iloc[0]
top, low = by_dim.loc[by_dim[col].idxmax()], by_dim.loc[by_dim[col].idxmin()]

# ---------- headline numbers ----------
k1, k2, k3 = st.columns(3)
k1.metric(f"{measure}, whole selection", fmt_value(overall, m["fmt"]), help=m["help"], border=True)
k2.metric(f"Highest {label.lower()}", f"{top[dim]} · {fmt_value(top[col], m['fmt'])}",
          help=f"Lowest: {low[dim]} · {fmt_value(low[col], m['fmt'])}", border=True)
if m["fmt"] == "pct":
    spread = f"{(top[col] - low[col]) * 100:.2f} pp"
else:
    spread = f"{top[col] / low[col] - 1:+.1%}" if low[col] else "–"
k3.metric("Gap highest vs lowest", spread if len(by_dim) > 1 else "–",
          help=f"How far {top[dim]} is above {low[dim]}. A small gap means the {label.lower()}s behave alike.",
          border=True)

# ---------- ranking ----------
st.subheader(f"{measure} by {label.lower()}")
st.caption("Sorted high to low" + (", with each one's share of the total." if m["additive"] else "."))
st.altair_chart(ranking_chart(by_dim, dim, measure), width="stretch")

# ---------- trend ----------
t1, t2 = st.columns([3, 1], vertical_alignment="bottom")
t1.subheader(f"{measure} over time, per {label.lower()}")
grain = t2.segmented_control("Grain", ["Day", "Month"], default="Day", key="x_grain") or "Day"
over_time = aggregate(by_period(df, grain), ["period", dim])
if measure == "Failure rate":
    # a rate hides volume; the outcome split shows the failed share of each bar directly
    st.caption("Each bar is all transactions of that period: failed at the bottom (its share reads off the "
               "axis), successful on top. One panel each, on the same 0–100% scale. Hover for counts.")
    st.altair_chart(outcome_multiples(over_time, dim, grain), width="content")
else:
    if grain == "Month":
        over_time = over_time.merge(monthly_summary(df)[["period", "is_partial"]], on="period")
    st.caption("One panel each, all on the same scale: compare levels across panels and the pattern within each. "
               + ("Solid line: 7-day average (smooths the weekday swing). " if grain == "Day" else "")
               + "Dashed line: straight-line trend over the range"
               + (", complete months only." if grain == "Month" else "."))
    st.altair_chart(trend_multiples(over_time, dim, measure, grain), width="content")

# ---------- cross-section ----------
others = [d for d in DIMENSIONS if d != label]
x1, x2 = st.columns([3, 1], vertical_alignment="bottom")
cross_label = x2.selectbox("Cross with", others, key="x_cross")
cross = DIMENSIONS[cross_label]
x1.subheader(f"{measure} by {label.lower()} and {cross_label.lower()}")
st.caption("Follows the measure picked at the top (e.g. Transactions for counts). Color follows the legend. Its range spans the lowest to the highest cell, so even small "
           "differences stand out: read the printed values to judge how big they really are.")
st.altair_chart(heatmap(aggregate(df, [dim, cross]), dim, cross, measure), width="stretch")

# ---------- table ----------
with st.expander("All measures by " + label.lower()):
    table = by_dim[[dim, "credits_charged", "transactions", "failure_rate", "credits_failed"]]
    st.dataframe(table.sort_values("credits_charged", ascending=False), hide_index=True, width="stretch",
                 column_config={
                     dim: st.column_config.TextColumn(label),
                     "credits_charged": st.column_config.NumberColumn("Credits charged", format="%.0f"),
                     "transactions": st.column_config.NumberColumn("Transactions", format="%d"),
                     "failure_rate": st.column_config.NumberColumn("Failure rate", format="percent"),
                     "credits_failed": st.column_config.NumberColumn("Failed credits", format="%.0f"),
                 })
