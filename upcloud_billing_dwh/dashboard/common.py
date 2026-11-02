# dashboard/common.py
# Shared data access, filters and chart helpers for every page.
from pathlib import Path

import altair as alt
import duckdb
import numpy as np
import pandas as pd
import streamlit as st

# The dashboard reads the published snapshot, never the build database dbt writes: the runner
# swaps serving.duckdb in atomically after a run passes its tests (scripts/run_pipeline.py, publish),
# so the pipeline can run while the app is open. Resolved relative to this file.
DB_PATH = Path(__file__).resolve().parent.parent / "serving.duckdb"
# schemas of the domain marts: derived from the folder path (macros/generate_schema_name.sql)
MARTS = "marts__domain_finance"  # report_billing_daily
CLIENT_OPS_MARTS = "marts__domain_client_ops"  # report_client_usage_daily
# pipeline metadata written by scripts/run_pipeline.py (not dbt): must match the names there
OPS = "ops__ingestion"  # billing_file_manifest, reconcile_log
SERVING = "ops__serving"  # snapshot: published_at, data_through

# categorical slots in fixed order (validated palette): colors follow the entity, so each
# dimension's full value list is mapped once and filtering never repaints. Dark mode uses
# the same hues stepped for a dark surface, not the light values.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MUTED = "#a3a29d"

# natural order for tiers (stack order, legend order), instead of alphabetical
TIER_ORDER = ["free", "basic", "pro", "enterprise"]

DIMENSIONS = {
    "Country": "country",
    "Resource type": "resource_type",
    "Service tier": "service_tier",
    "Operation type": "operation_type",
}


# ---------- data access ----------

def snapshot_version():
    """Changes every time the runner publishes a new serving.duckdb (new file, new mtime)."""
    try:
        return DB_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return None


@st.cache_data(show_spinner=False, max_entries=256)
def _query(sql, version):
    # `version` is part of the cache key: a new snapshot invalidates every cached query at once
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.sql(sql).df()


def q(sql):
    version = snapshot_version()
    if version is None:
        st.warning("No published data yet: run the pipeline first (make backfill).")
        st.stop()
    try:
        return _query(sql, version)
    except duckdb.IOException as e:
        st.error(f"Could not open serving.duckdb.\n\n{e}")
        st.stop()
    except duckdb.CatalogException as e:
        st.error(f"A table is missing. Run dbt first.\n\n{e}")
        st.stop()


def table_exists(schema, table):
    return not q(f"select 1 from information_schema.tables "
                 f"where table_schema = '{schema}' and table_name = '{table}'").empty


def load_daily():
    df = q(f"select * from {MARTS}.report_billing_daily")
    df["billed_at"] = pd.to_datetime(df["billed_at"])
    return df


def load_active_users():
    """Monthly active users from the client-level daily report: distinct users don't add up, so each
    window is a count(distinct user_id) over the days it covers. The current month is month-to-date
    through the latest day loaded, compared with the same days of the previous month."""
    df = q(f"""
        with activity as (
            select date_trunc('month', billed_at)::date as billed_year_month, billed_at, user_id, service_tier
            from {CLIENT_OPS_MARTS}.report_client_usage_daily
        ),
        months as (
            select
                billed_year_month,
                -- closed months run to their last day, the current month to the latest day loaded
                least(last_day(billed_year_month), (select max(billed_at) from activity)) as data_through,
                count(distinct user_id) as total_active_users,
                count(distinct user_id) filter (where service_tier = 'free') as total_active_free_tier_users,
                count(distinct user_id) filter (where service_tier = 'basic') as total_active_basic_tier_users,
                count(distinct user_id) filter (where service_tier = 'pro') as total_active_pro_tier_users,
                count(distinct user_id) filter (where service_tier = 'enterprise') as total_active_enterprise_tier_users
            from activity
            group by billed_year_month
        )
        select
            months.*,
            months.data_through < last_day(months.billed_year_month) as is_partial_month,
            -- previous month up to the same day of the month: null for the first month loaded
            (select nullif(count(distinct user_id), 0) from activity
             where activity.billed_year_month = months.billed_year_month - interval 1 month
               and day(activity.billed_at) <= day(months.data_through)) as prior_month_same_period_active_users
        from months
        order by billed_year_month
    """)
    df["billed_year_month"] = pd.to_datetime(df["billed_year_month"])
    df["data_through"] = pd.to_datetime(df["data_through"])
    return df


def load_daily_active_users():
    """Distinct users with at least one transaction, per billing day."""
    df = q(f"""
        select billed_at, count(distinct user_id) as active_users
        from {CLIENT_OPS_MARTS}.report_client_usage_daily
        group by billed_at
        order by billed_at
    """)
    df["billed_at"] = pd.to_datetime(df["billed_at"])
    return df


# ---------- shared state (set in app.py) ----------

def daily():
    """report_billing_daily filtered by the sidebar dimensions and date range."""
    return st.session_state["daily"]


def daily_all_dates():
    """Filtered by the sidebar dimensions only: month-to-date KPIs ignore the date range."""
    return st.session_state["daily_dims"]


def domain(column):
    """Full, sorted value list of a dimension, so colors stay fixed per entity."""
    return st.session_state["domains"][column]


# ---------- metrics ----------

def failure_rate(df):
    total = df["total_transactions"].sum()
    return df["failed_transactions"].sum() / total if total else None


def mtd_vs_prior_period(df, value_fn):
    """Value month-to-date and over the same days of the previous month (None if not loaded)."""
    through = df["billed_at"].max()
    month_start = through.replace(day=1)
    prior_start = month_start - pd.DateOffset(months=1)
    current = df[df["billed_at"] >= month_start]
    prior = df[(df["billed_at"] >= prior_start) & (df["billed_at"] < month_start)
               & (df["billed_at"].dt.day <= through.day)]
    return value_fn(current), (value_fn(prior) if not prior.empty else None), through


def pct_delta(current, prior):
    # prior is NA when the previous month isn't loaded (NULL from the mart)
    if current is None or prior is None or pd.isna(prior) or prior == 0:
        return None
    return f"{(current - prior) / prior:+.1%} vs same period last month"


def credits(v):
    # credits are a platform unit, not money (see fct_resource_usage_invoices): no currency symbol
    return f"{v / 1e6:,.1f}M cr" if abs(v) >= 1e6 else f"{v:,.0f} cr"


# ---------- charts ----------

def _is_dark():
    theme = getattr(st.context, "theme", None)
    return getattr(theme, "type", None) == "dark"


def series():
    return SERIES_DARK if _is_dark() else SERIES_LIGHT


def text_secondary():
    """Axis label ink: secondary text, stepped per theme (never the series color)."""
    return "#c3c2b7" if _is_dark() else "#52514e"


def surface():
    """Streamlit's page background (used for the 2px gap around marks)."""
    return "#0e1117" if _is_dark() else "#ffffff"


def ordered_domain(column, values):
    values = sorted(values)
    if column == "service_tier" and set(values) <= set(TIER_ORDER):
        return [t for t in TIER_ORDER if t in values]
    return values


def num_axis(fmt, **kwargs):
    """Value axis. SI formats print billions as 'B' (1.4B), not the SI 'G' (1.4G)."""
    if fmt.endswith("s"):
        return alt.Axis(labelExpr=f"replace(format(datum.value, '{fmt}'), 'G', 'B')", **kwargs)
    return alt.Axis(format=fmt, **kwargs)


def _x_time(field, grain):
    fmt = "%b %Y" if grain == "Month" else "%d %b"
    return alt.X(f"{field}:T", title=None, axis=alt.Axis(format=fmt, grid=False, labelColor=text_secondary()))


def bars_with_trend(df, x, y, *, y_title, y_format, window=7, height=320):
    """Daily bars with a trailing `window`-day average line on top (smooths the weekday swing)."""
    df = df.assign(trend=df[y].rolling(window, min_periods=window).mean())
    tooltip = [alt.Tooltip(f"{x}:T", title="Date", format="%d %b %Y"),
               alt.Tooltip(f"{y}:Q", title=y_title, format=y_format),
               alt.Tooltip("trend:Q", title=f"{window}-day average", format=y_format)]
    base = alt.Chart(df).encode(x=_x_time(x, "Day"))
    bars = base.mark_bar(color=series()[0], opacity=0.55).encode(
        y=alt.Y(f"{y}:Q", title=y_title, axis=num_axis(y_format, labelColor=text_secondary())), tooltip=tooltip)
    trend = base.mark_line(color=text_secondary(), strokeWidth=2).encode(y="trend:Q", tooltip=tooltip)
    return alt.layer(bars, trend).properties(height=height)


def by_period(df, grain):
    """Adds a `period` column: the billing day, or the first day of its month."""
    out = df.copy()
    out["period"] = out["billed_at"] if grain == "Day" else out["billed_at"].dt.to_period("M").dt.to_timestamp()
    return out


# ---------- measures ----------
# Every measure is computed AFTER grouping, from additive sums, so ratios are never averaged.

BASE_COLUMNS = ["credits_charged", "credits_failed", "total_transactions",
                "successful_transactions", "failed_transactions"]

MEASURES = {
    "Credits charged": {"col": "credits_charged", "fmt": "credits", "axis": "~s", "additive": True,
                        "help": "Credits from successful transactions (platform unit, not money)"},
    "Transactions": {"col": "transactions", "fmt": "int", "axis": "~s", "additive": True,
                     "help": "All billing transactions, successful or not"},
    "Failure rate": {"col": "failure_rate", "fmt": "pct", "axis": ".1%", "additive": False,
                     "help": "Failed / total transactions"},
    "Failed credits": {"col": "credits_failed", "fmt": "credits", "axis": "~s", "additive": True,
                       "help": "Credits carried by failed transactions (not charged)"},
}


def aggregate(df, keys):
    """Sum the additive columns by `keys`, then derive every measure."""
    g = df.groupby(keys, as_index=False)[BASE_COLUMNS].sum() if keys else df[BASE_COLUMNS].sum().to_frame().T
    g["credits_charged"] = g["credits_charged"].astype(float)
    g["credits_failed"] = g["credits_failed"].astype(float)
    g["transactions"] = g["total_transactions"].astype(float)
    g["failure_rate"] = g["failed_transactions"] / g["total_transactions"].where(g["total_transactions"] > 0)
    return g


def fmt_value(v, kind):
    if pd.isna(v):
        return "–"
    return {"credits": lambda: credits(v), "int": lambda: f"{v:,.0f}",
            "pct": lambda: f"{v:.2%}"}[kind]()


# ---------- charts ----------

def _color_scale(column):
    values = domain(column)
    return alt.Scale(domain=values, range=series()[:len(values)])


def ranking_chart(g, dim, measure):
    """Horizontal bars, one per value of `dim`, sorted high to low, value labelled at the bar end.
    Bars keep each entity's fixed color, so the same country is the same color everywhere."""
    m = MEASURES[measure]
    data = g.copy()
    data["label"] = data[m["col"]].map(lambda v: fmt_value(v, m["fmt"]))
    if m["additive"]:
        total = data[m["col"]].sum()
        data["share"] = data[m["col"]] / total if total else 0
        data["label"] = data["label"] + data["share"].map(lambda v: f"  ({v:.0%})")
    # extra right margin so the labels at the bar ends are never clipped
    x_max = float(data[m["col"]].max()) * 1.3 if len(data) and data[m["col"]].max() > 0 else 1
    base = alt.Chart(data).encode(
        # explicit order: sort="-x" gets dropped when layers share the y scale
        y=alt.Y(f"{dim}:N", sort=data.sort_values(m["col"], ascending=False)[dim].tolist(), title=None, axis=alt.Axis(labelColor=text_secondary(), labelLimit=200)),
        x=alt.X(f"{m['col']}:Q", title=measure, scale=alt.Scale(domain=[0, x_max], nice=False),
                axis=num_axis(m["axis"], labelColor=text_secondary(), tickCount=5)),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.7}).encode(
        color=alt.Color(f"{dim}:N", scale=_color_scale(dim), legend=None),
        tooltip=[alt.Tooltip(f"{dim}:N", title=dim.replace("_", " ").capitalize()),
                 alt.Tooltip("label:N", title=measure)],
    )
    labels = base.mark_text(align="left", dx=6, color=text_secondary()).encode(text="label:N")
    return alt.layer(bars, labels).properties(height=max(120, 46 * len(data))).configure_view(strokeWidth=0)


def trend_multiples(g, dim, measure, grain, *, columns=3, panel_width=330, panel_height=170):
    """One small panel per value of `dim` (not stacked), same y-axis, so trends and levels compare."""
    m = MEASURES[measure]
    date_fmt = "%d %b %Y" if grain == "Day" else "%b %Y"
    data = g.copy()
    data["label"] = data[m["col"]].map(lambda v: fmt_value(v, m["fmt"]))
    c = m["col"]
    data = data.sort_values([dim, "period"])
    if grain == "Day":
        # 7-day trailing average per panel: removes the weekday swing so a slow drift shows
        data["avg7"] = (data.set_index("period").groupby(dim)[c]
                        .rolling("7D", min_periods=7).mean().reset_index(drop=True).values)
    # the dashed linear fit leaves out partial months, which would read as a drop
    data["in_fit"] = ~data["is_partial"] if "is_partial" in data else True
    tooltip = [alt.Tooltip(f"{dim}:N", title=dim.replace("_", " ").capitalize()),
               alt.Tooltip("period:T", title="Date", format=date_fmt),
               alt.Tooltip("label:N", title=measure)]
    if grain == "Day":
        tooltip.append(alt.Tooltip("avg7:Q", title="7-day average", format=m["axis"].replace("~s", ",.0f")))
    # days on a time axis (the lines need it); months as one band each, so 2-3 bars stay readable
    axis = alt.Axis(format="%d %b" if grain == "Day" else "%b %Y", labelOverlap=True, labelAngle=0, grid=False,
                    labelColor=text_secondary())
    x = alt.X("period:T", title=None, axis=axis) if grain == "Day" else \
        alt.X("yearmonth(period):O", title=None, axis=alt.Axis(formatType="time", **axis.to_dict()))
    base = alt.Chart(data).encode(x=x)
    y = alt.Y(f"{c}:Q", title=measure, axis=num_axis(m["axis"], labelColor=text_secondary()))
    bars = base.mark_bar(cornerRadiusEnd=2).encode(
        y=y, color=alt.Color(f"{dim}:N", scale=_color_scale(dim), legend=None), tooltip=tooltip,
        opacity=alt.value(0.6) if grain == "Day" else alt.condition("datum.in_fit", alt.value(1), alt.value(0.45)))
    fit = base.transform_filter("datum.in_fit").transform_regression("period", c).mark_line(
        color=text_secondary(), strokeDash=[5, 3], strokeWidth=1.5).encode(y=f"{c}:Q")
    layers = [bars, fit]
    if grain == "Day":
        layers.insert(1, base.mark_line(color=text_secondary(), strokeWidth=2).encode(y="avg7:Q"))
    chart = alt.layer(*layers, data=data).properties(width=panel_width, height=panel_height)
    return chart.facet(
        facet=alt.Facet(f"{dim}:N", title=None, sort=domain(dim),
                        header=alt.Header(labelFontSize=13, labelFontWeight="bold", labelAnchor="start")),
        columns=columns,
    ).configure_view(strokeWidth=0)


def heatmap(g, rows, cols, measure):
    """rows x cols grid colored by the measure (one-hue sequential ramp), value printed in each cell.
    The color range spans min..max of the cells so small differences stay visible."""
    m = MEASURES[measure]
    data = g.copy()
    data["label"] = data[m["col"]].map(lambda v: fmt_value(v, m["fmt"]))
    lo, hi = data[m["col"]].min(), data[m["col"]].max()
    ramp = ["#cde2fb", "#104281"] if not _is_dark() else ["#184f95", "#b7d3f6"]
    # cell text flips to stay readable on the dark end of the ramp
    strong = (data[m["col"]] - lo) / (hi - lo) > 0.55 if hi > lo else pd.Series(False, index=data.index)
    data["ink"] = strong.map({True: "#ffffff" if not _is_dark() else "#0b0b0b",
                              False: "#0b0b0b" if not _is_dark() else "#f0efec"})
    base = alt.Chart(data).encode(
        x=alt.X(f"{cols}:N", title=None, sort=domain(cols),
                axis=alt.Axis(orient="top", labelAngle=0, labelColor=text_secondary(), labelLimit=160)),
        y=alt.Y(f"{rows}:N", title=None, sort=domain(rows), axis=alt.Axis(labelColor=text_secondary(), labelLimit=200)),
    )
    n_rows = data[rows].nunique()
    height = max(120, 48 * n_rows)
    cells = base.mark_rect(stroke=surface(), strokeWidth=2, cornerRadius=3).encode(
        color=alt.Color(f"{m['col']}:Q", scale=alt.Scale(range=ramp, domain=[lo, hi], zero=False),
                        # ratios sit in a narrow band (e.g. 4.98%-5.03%): two decimals keep legend ticks distinct
                        legend=alt.Legend(title=measure, orient="right", gradientLength=max(60, height - 50),
                                          labelExpr=("format(datum.value, '.2%')" if m["fmt"] == "pct" else
                                                     f"replace(format(datum.value, '.3~s'), 'G', 'B')"))),
        tooltip=[alt.Tooltip(f"{rows}:N", title=rows.replace("_", " ").capitalize()),
                 alt.Tooltip(f"{cols}:N", title=cols.replace("_", " ").capitalize()),
                 alt.Tooltip("label:N", title=measure)],
    )
    text = base.mark_text(fontSize=12).encode(text="label:N", color=alt.Color("ink:N", scale=None, legend=None))
    # the cell color (quantitative ramp) and the text ink (literal colors) must not share a scale
    return alt.layer(cells, text).resolve_scale(color="independent").properties(
        height=height).configure_view(strokeWidth=0)


def monthly_summary(df):
    """One row per month with every measure, plus how far the data runs and whether the month is complete."""
    g = aggregate(by_period(df, "Month"), ["period"]).sort_values("period")
    first, latest = df["billed_at"].min(), df["billed_at"].max()
    month_end = g["period"] + pd.offsets.MonthEnd(0)
    g["data_through"] = month_end.where(month_end <= latest, latest)
    g["is_partial"] = (g["data_through"] < month_end) | (g["period"] < first)
    g["month"] = g["period"].dt.strftime("%b %Y") + g["is_partial"].map({True: " (partial)", False: ""})
    return g.reset_index(drop=True)


# status colors (reserved: never used for a series) - always paired with a text label
STATUS_GOOD, STATUS_CRITICAL = "#0ca30c", "#d03b3b"


def outcome_multiples(g, dim, grain, *, columns=3, panel_width=330, panel_height=170):
    """100% stacked bars per period: failed (red, at the baseline so its share reads off the axis)
    vs successful (green). One panel per value of `dim`, all on the same 0-100% scale."""
    rows = []
    for outcome, col in (("Failed", "failed_transactions"), ("Successful", "successful_transactions")):
        part = g[["period", dim, col, "total_transactions"]].rename(columns={col: "count"})
        part["outcome"] = outcome
        rows.append(part)
    data = pd.concat(rows)
    data["share"] = data["count"] / data["total_transactions"]
    data["stack_order"] = data["outcome"].map({"Failed": 0, "Successful": 1})
    date_fmt = "%d %b %Y" if grain == "Day" else "%b %Y"
    chart = alt.Chart(data).mark_bar(stroke=surface(), strokeWidth=1).encode(
        x=alt.X(f"{'yearmonthdate' if grain == 'Day' else 'yearmonth'}(period):O", title=None,
                axis=alt.Axis(format="%d %b" if grain == "Day" else "%b %Y", formatType="time", labelAngle=0,
                              labelOverlap=True, grid=False, labelColor=text_secondary())),
        y=alt.Y("count:Q", stack="normalize", title="Share of transactions",
                axis=alt.Axis(format=".0%", labelColor=text_secondary())),
        color=alt.Color("outcome:N", scale=alt.Scale(domain=["Failed", "Successful"],
                                                     range=[STATUS_CRITICAL, STATUS_GOOD]),
                        legend=alt.Legend(title=None, orient="top")),
        order=alt.Order("stack_order:Q"),
        tooltip=[alt.Tooltip(f"{dim}:N", title=dim.replace("_", " ").capitalize()),
                 alt.Tooltip("period:T", title="Date", format=date_fmt),
                 alt.Tooltip("outcome:N", title="Outcome"),
                 alt.Tooltip("count:Q", title="Transactions", format=","),
                 alt.Tooltip("share:Q", title="Share", format=".2%")],
    ).properties(width=panel_width, height=panel_height)
    return chart.facet(
        facet=alt.Facet(f"{dim}:N", title=None, sort=domain(dim),
                        header=alt.Header(labelFontSize=13, labelFontWeight="bold", labelAnchor="start")),
        columns=columns,
    ).configure_view(strokeWidth=0)


# diverging pair (blue = above baseline, red = below), stepped per theme
def _diverging():
    return ("#3987e5", "#e66767") if _is_dark() else ("#2a78d6", "#e34948")


def deviation_bars(data, dim, value_col, label_col, *, value_title, value_format, higher_is_bad=False):
    """Diverging horizontal bars around zero: how far each segment is from its own baseline.
    Sorted by deviation, so the biggest outliers sit at the ends. For measures where higher is worse
    (failure rate) the poles swap, so red always means the unwelcome direction."""
    good, bad = _diverging()
    above, below = (bad, good) if higher_is_bad else (good, bad)
    data = data.copy()
    data["direction"] = data[value_col].map(lambda v: "Higher than usual" if v >= 0 else "Lower than usual")
    span = float(data[value_col].abs().max()) * 1.6 or 0.01
    base = alt.Chart(data).encode(
        # explicit order: sort="-x" gets dropped when layers share the y scale
        y=alt.Y(f"{dim}:N", sort=data.sort_values(value_col, ascending=False)[dim].tolist(), title=None, axis=alt.Axis(labelColor=text_secondary(), labelLimit=200)),
        x=alt.X(f"{value_col}:Q", title=value_title, scale=alt.Scale(domain=[-span, span]),
                axis=num_axis(value_format, labelColor=text_secondary(), tickCount=5)),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.6}).encode(
        color=alt.Color("direction:N", scale=alt.Scale(domain=["Higher than usual", "Lower than usual"],
                                                       range=[above, below]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip(f"{dim}:N", title=dim.replace("_", " ").capitalize()),
                 alt.Tooltip(f"{label_col}:N", title=value_title)],
    )
    # labels just past the bar end: left-aligned on the positive side, right-aligned on the negative
    pos = base.transform_filter(f"datum.{value_col} >= 0").mark_text(align="left", dx=6, color=text_secondary())
    neg = base.transform_filter(f"datum.{value_col} < 0").mark_text(align="right", dx=-6, color=text_secondary())
    pos, neg = (layer.encode(text=f"{label_col}:N") for layer in (pos, neg))
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=MUTED).encode(x="x:Q")
    return alt.layer(bars, pos, neg, zero).properties(height=max(120, 46 * len(data))).configure_view(strokeWidth=0)



def grouped_bars(data, period_col, dim, measure, *, partial_col=None, trend=False, height=320):
    """Grouped bars: one group per period (x), one bar per value of `dim` inside it, in that value's
    fixed color. Reads both ways: each group compares the values, the same color across groups shows
    how one value moved over time. A partial period is faded so it isn't read as a drop."""
    m = MEASURES[measure]
    data = data.copy()
    data["label"] = data[m["col"]].map(lambda v: fmt_value(v, m["fmt"]))
    periods = list(dict.fromkeys(data[period_col]))  # keep the caller's order
    tooltip = [alt.Tooltip(f"{period_col}:N", title="Period"),
               alt.Tooltip(f"{dim}:N", title=dim.replace("_", " ").capitalize()),
               alt.Tooltip("label:N", title=measure)]
    encoding = dict(
        x=alt.X(f"{period_col}:N", title=None, sort=periods,
                axis=alt.Axis(labelAngle=0, labelColor=text_secondary(), grid=False),
                scale=alt.Scale(paddingInner=0.25)),
        xOffset=alt.XOffset(f"{dim}:N", sort=domain(dim), scale=alt.Scale(paddingInner=0.08)),
        y=alt.Y(f"{m['col']}:Q", title=measure, axis=num_axis(m["axis"], labelColor=text_secondary())),
        color=alt.Color(f"{dim}:N", scale=_color_scale(dim), legend=alt.Legend(title=None, orient="top")),
        tooltip=tooltip,
    )
    if partial_col:
        encoding["opacity"] = alt.condition(f"datum.{partial_col}", alt.value(0.45), alt.value(1))
    chart = alt.Chart(data).mark_bar(cornerRadiusEnd=3).encode(**encoding)
    if trend:
        # dashed straight-line fit per value across the periods, through each value's own bars;
        # partial periods are left out of the fit (they would read as a drop)
        c = m["col"]
        fit = data[~data[partial_col]] if partial_col else data
        fit = fit.assign(i=fit[period_col].map(periods.index))
        rows = []
        for value, g in fit.groupby(dim):
            if len(g) >= 2:
                slope, intercept = np.polyfit(g["i"], g[c], 1)
                rows.append(g[[period_col, dim]].assign(trend=slope * g["i"] + intercept))
        if rows:
            line = alt.Chart(pd.concat(rows)).mark_line(strokeDash=[5, 3], strokeWidth=2).encode(
                x=encoding["x"], xOffset=encoding["xOffset"], y="trend:Q",
                color=alt.Color(f"{dim}:N", scale=_color_scale(dim), legend=None))
            chart = alt.layer(chart, line)
    return chart.properties(height=height).configure_view(strokeWidth=0)
