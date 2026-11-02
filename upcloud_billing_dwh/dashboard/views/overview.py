import pandas as pd
import streamlit as st

from common import (DIMENSIONS, MEASURES, aggregate, by_period, daily_all_dates, deviation_bars, credits,
                    fmt_value, grouped_bars, load_active_users, monthly_summary)

LATEST_DAY, MTD, HISTORY = "Latest day", "Month to date", "All history"

st.title("Overview")
period = st.segmented_control("Period", [LATEST_DAY, MTD, HISTORY], default=MTD, key="ov_period") or MTD

# every loaded day for the sidebar dimension filters: the period picks its own window,
# so the sidebar date slider doesn't apply here (it drives the Explore page)
dims = daily_all_dates()
latest = dims["billed_at"].max()
first = dims["billed_at"].min()
active = load_active_users()


def delta(current, prior, kind, label):
    if prior is None or pd.isna(prior) or pd.isna(current):
        return None
    if kind == "pct":
        return f"{(current - prior) * 100:+.2f} pp {label}"
    return f"{(current - prior) / prior:+.1%} {label}" if prior else None


def tiles(current, prior, compare_label, title_suffix, extra=None):
    """Credits charged, transactions, failure rate and failed credits, each vs the comparison."""
    cur = aggregate(current, []).iloc[0]
    pri = aggregate(prior, []).iloc[0] if prior is not None and not prior.empty else None
    shown = ["Credits charged", "Transactions", "Failure rate", "Failed credits"]
    cols = st.columns(len(shown) + (1 if extra else 0))
    for col, name in zip(cols, shown):
        m = MEASURES[name]
        col.metric(f"{name} {title_suffix}".strip(), fmt_value(cur[m["col"]], m["fmt"]),
                   delta(cur[m["col"]], None if pri is None else pri[m["col"]], m["fmt"], compare_label),
                   delta_color="inverse" if name in ("Failure rate", "Failed credits") else "normal",
                   help=m["help"], border=True)
    if extra:
        cols[-1].metric(**extra, border=True)


def group_controls(key):
    """Dimension and measure pickers for the grouped bar charts."""
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    label = c1.segmented_control("Break down by", list(DIMENSIONS), default="Country", key=f"{key}_dim") or "Country"
    measure = c2.segmented_control("Measure", list(MEASURES), default="Credits charged", key=f"{key}_measure") or "Credits charged"
    return label, DIMENSIONS[label], measure


def daily_baseline(window, keys, n_days):
    """Average day over the window: additive measures divided by the number of days,
    rates recomputed from the window's sums (never averaged)."""
    g = aggregate(window, keys)
    for c in ("credits_charged", "transactions", "credits_failed"):
        g[c] = g[c] / n_days
    return g


if period == LATEST_DAY:
    # daily credits swing +-40% from one day to the next, so the day before is a noisy baseline:
    # compare with the average day of the week before instead (the day before stays in the tooltip)
    prev_day = latest - pd.Timedelta(days=1)
    day = dims[dims["billed_at"] == latest]
    window = dims[(dims["billed_at"] < latest) & (dims["billed_at"] >= latest - pd.Timedelta(days=7))]
    n_days = window["billed_at"].nunique()
    shown = ["Credits charged", "Transactions", "Failure rate", "Failed credits"]

    st.caption(f"**{latest:%A %d %b %Y}**, the latest day loaded (EOD), compared with the average day "
               f"of the {n_days} days before it.")
    cur = aggregate(day, []).iloc[0]
    base = daily_baseline(window, [], n_days).iloc[0] if n_days else None
    prev = dims[dims["billed_at"] == prev_day]
    prev_vals = aggregate(prev, []).iloc[0] if not prev.empty else None

    for col, name in zip(st.columns(len(shown)), shown):
        m, c = MEASURES[name], MEASURES[name]["col"]
        hint = f"{m['help']}."
        if base is not None:
            hint += f" {n_days}-day average: {fmt_value(base[c], m['fmt'])}."
        if prev_vals is not None:
            hint += f" {prev_day:%d %b}: {fmt_value(prev_vals[c], m['fmt'])}."
        col.metric(name, fmt_value(cur[c], m["fmt"]),
                   delta(cur[c], None if base is None else base[c], m["fmt"], f"vs {n_days}-day avg"),
                   delta_color="inverse" if name in ("Failure rate", "Failed credits") else "normal",
                   help=hint, border=True)

    if not n_days:
        st.info("No earlier days loaded, so there is no baseline to compare with yet.")
        st.stop()

    # ---------- where the day differed ----------
    st.subheader("Where the day was different")
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    dev_label = c1.segmented_control("Break down by", list(DIMENSIONS), default="Country", key="ld_dim") or "Country"
    dev_measure = c2.segmented_control("Measure", ["Credits charged", "Transactions", "Failure rate"],
                                       default="Credits charged", key="ld_measure") or "Credits charged"
    dim, m = DIMENSIONS[dev_label], MEASURES[dev_measure]
    c = m["col"]
    seg = aggregate(day, [dim]).merge(daily_baseline(window, [dim], n_days)[[dim, c]], on=dim, suffixes=("", "_base"))
    if m["fmt"] == "pct":
        seg["dev"] = (seg[c] - seg[f"{c}_base"]) * 100
        seg["dev_label"] = seg["dev"].map(lambda v: f"{v:+.2f} pp")
        dev_title, dev_fmt = "Change vs 7-day average (pp)", "+.2f"
    else:
        seg["dev"] = seg[c] / seg[f"{c}_base"] - 1
        seg["dev_label"] = seg["dev"].map(lambda v: f"{v:+.1%}")
        dev_title, dev_fmt = "Change vs 7-day average", "+.0%"
    st.caption(f"Each {dev_label.lower()} against its own average day of the previous {n_days} days. "
               "A segment far from the others is where to look first.")
    st.altair_chart(deviation_bars(seg, dim, "dev", "dev_label", value_title=dev_title, value_format=dev_fmt,
                                   higher_is_bad=dev_measure == "Failure rate"),
                    width="stretch")

    # ---------- what made up the day ----------
    st.subheader(f"{latest:%d %b} by {dev_label.lower()}")
    table = seg[[dim, c, f"{c}_base", "dev"]].sort_values(c, ascending=False)
    if m["additive"]:
        table["share"] = table[c] / table[c].sum()
    value_format = {"credits": "%.0f", "pct": "percent", "int": "%d"}[m["fmt"]]
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        dim: st.column_config.TextColumn(dev_label),
        c: st.column_config.NumberColumn(f"{dev_measure}, {latest:%d %b}", format=value_format),
        f"{c}_base": st.column_config.NumberColumn(f"{n_days}-day average", format=value_format),
        "dev": st.column_config.NumberColumn("Change", format="%+.2f pp" if m["fmt"] == "pct" else "percent"),
        "share": st.column_config.NumberColumn("Share of the day", format="percent"),
    })

elif period == MTD:
    month_start = latest.replace(day=1)
    prior_start = month_start - pd.DateOffset(months=1)
    current = dims[dims["billed_at"] >= month_start]
    prior = dims[(dims["billed_at"] >= prior_start) & (dims["billed_at"] < month_start)]
    prior_same_days = prior[prior["billed_at"].dt.day <= latest.day]
    st.caption(f"**1–{latest.day} {latest:%b %Y}**, compared with the same days of {prior_start:%B}"
               + ("" if not prior.empty else " (not loaded, so no comparison)") + ".")

    month_row = active[active["billed_year_month"] == month_start]
    extra = None
    if not month_row.empty:
        row = month_row.iloc[0]
        prior_users = row.prior_month_same_period_active_users
        extra = dict(label="Active users", value=f"{int(row.total_active_users):,}",
                     delta=delta(row.total_active_users, None if pd.isna(prior_users) else prior_users,
                                 "int", "vs same days"),
                     help="All users: not affected by the sidebar filters (distinct counts don't add up).")
    tiles(current, prior_same_days, "vs same days", "MTD", extra)

    st.subheader("This month against last month")
    label, dim, measure = group_controls("mtd")
    same_days = f"1–{min(latest.day, prior['billed_at'].dt.day.max())}" if not prior.empty else ""
    parts = []
    if not prior_same_days.empty:
        prev_g = aggregate(prior_same_days, [dim])
        prev_g["period"] = f"{prior_start:%b %Y} ({same_days})"
        parts.append(prev_g)
    cur_g = aggregate(current, [dim])
    cur_g["period"] = f"{latest:%b %Y} (1–{latest.day})"
    parts.append(cur_g)
    st.caption(f"{measure} per {label.lower()}, same days of each month, so the two groups compare like for "
               "like. Same color = same value in both months.")
    st.altair_chart(grouped_bars(pd.concat(parts), "period", dim, measure), width="stretch")

else:  # all history, aggregated by month
    months = monthly_summary(dims)
    full = months[~months["is_partial"]]
    st.caption(f"Everything loaded, **{first:%d %b %Y} to {latest:%d %b %Y}** ({len(months)} months), "
               "aggregated by month. A partial month is faded, so it isn't read as a drop.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total credits charged", credits(months["credits_charged"].sum()), border=True)
    c2.metric("Avg credits per full month", credits(full["credits_charged"].mean()) if len(full) else "–", border=True,
              help="Complete months only")
    if len(full) >= 2:
        last, before = full.iloc[-1], full.iloc[-2]
        c3.metric(f"Credits charged {last['period']:%b %Y}", credits(last["credits_charged"]),
                  f"{last['credits_charged'] / before['credits_charged'] - 1:+.1%} vs {before['period']:%b}", border=True,
                  help="Latest complete month, compared with the one before")
    else:
        c3.metric("Latest full month vs previous", "–", border=True, help="Needs two complete months loaded")
    c4.metric("Failure rate, all history", fmt_value(aggregate(dims, []).iloc[0]["failure_rate"], "pct"),
              border=True)

    st.subheader("Month by month")
    label, dim, measure = group_controls("hist")
    by_month = aggregate(by_period(dims, "Month"), ["period", dim]).merge(
        months[["period", "month", "is_partial"]], on="period").sort_values("period")
    st.caption(f"{measure} per {label.lower()}, one group per month. Follow a color across the groups to see "
               "how that value moved; the dashed line is its straight-line trend over the complete months. A partial "
               "month is faded and left out of the trend, so it isn't read as a drop.")
    st.altair_chart(grouped_bars(by_month, "month", dim, measure, partial_col="is_partial", trend=True), width="stretch")

    st.subheader("Monthly totals")
    table = months.merge(active[["billed_year_month", "total_active_users"]],
                         left_on="period", right_on="billed_year_month", how="left")
    table["mom"] = table["credits_charged"].pct_change()
    st.dataframe(
        table[["month", "credits_charged", "mom", "transactions", "failure_rate", "total_active_users"]],
        hide_index=True, width="stretch",
        column_config={
            "month": st.column_config.TextColumn("Month"),
            "credits_charged": st.column_config.NumberColumn("Credits charged", format="%.0f"),
            "mom": st.column_config.NumberColumn("vs previous month", format="percent",
                                                 help="A partial month's change is not comparable"),
            "transactions": st.column_config.NumberColumn("Transactions", format="%d"),
            "failure_rate": st.column_config.NumberColumn("Failure rate", format="percent"),
            "total_active_users": st.column_config.NumberColumn("Active users", format="%d",
                                                                help="All users, not affected by the filters"),
        })
