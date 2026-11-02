# dashboard/app.py
# run from upcloud_billing_dwh/ with the same Python as dbt (DuckDB 2.x reads the file):
#   python3 -m streamlit run dashboard/app.py
# reads serving.duckdb, the snapshot the pipeline publishes after each successful run, so the
# pipeline can run while the app is open: new data shows up within ~30s (see _watch_snapshot)
from datetime import timedelta

import streamlit as st

from common import DIMENSIONS, SERVING, load_daily, ordered_domain, q, snapshot_version

st.set_page_config(page_title="Billing metrics", layout="wide")

daily = load_daily()
if daily.empty:
    st.warning("report_billing_daily is empty. Run the pipeline first (make backfill).")
    st.stop()

data_through = daily["billed_at"].max()
st.session_state["domains"] = {col: ordered_domain(col, daily[col].unique()) for col in DIMENSIONS.values()}


@st.fragment(run_every=30)
def _watch_snapshot():
    # polls the snapshot file: when the pipeline publishes a new one, rerun the whole app so
    # every page reads the new data (queries are cached per snapshot, see common.q)
    version = snapshot_version()
    seen = st.session_state.setdefault("snapshot_version", version)
    if version != seen:
        st.session_state["snapshot_version"] = version
        st.rerun(scope="app")
    published = q(f"select published_at from {SERVING}.snapshot")["published_at"].iloc[0]
    st.caption(f"**Data through {data_through:%d %b %Y}** · published {published:%d %b %H:%M}  \n"
               "Loaded once a day (EOD): the latest day is yesterday, no intraday data. "
               "Refreshes by itself when the pipeline publishes.")


# ---------- pages, and which sidebar filters each one actually applies ----------
pages = st.navigation([
    st.Page("views/overview.py", title="Overview", icon=":material/dashboard:", default=True),
    st.Page("views/explore.py", title="Explore", icon=":material/travel_explore:"),
    st.Page("views/active_users.py", title="Active users", icon=":material/group:"),
    st.Page("views/data_health.py", title="Data health", icon=":material/monitor_heart:"),
])
# Overview picks its own window (latest day / MTD / history), so only Explore uses the date range;
# Active users (distinct counts) and Data health read neither
show_dates = pages.title == "Explore"
show_dims = pages.title in ("Overview", "Explore")

# Streamlit drops a widget's value on runs where it isn't drawn: re-store them so the filters
# survive a visit to a page that hides them
FILTER_KEYS = ["date_range", "date_preset"] + [f"filter_{col}" for col in DIMENSIONS.values()]
for key in FILTER_KEYS:
    if key in st.session_state:
        st.session_state[key] = st.session_state[key]

# ---------- shared sidebar filters ----------
with st.sidebar:
    _watch_snapshot()

    min_day, max_day = daily["billed_at"].min().date(), data_through.date()
    presets = {"7d": 7, "14d": 14, "30d": 30, "All": None}

    # initialise once (and reset if new data moved the bounds); the slider reads it via its key
    current = st.session_state.get("date_range")
    previous_max = st.session_state.get("max_day_seen")
    if not current or current[0] < min_day or current[1] > max_day:
        st.session_state["date_range"] = (min_day, max_day)
    elif previous_max and current[1] == previous_max and max_day > previous_max:
        # a new day was published: a range that ended on the latest day keeps following it
        days = presets.get(st.session_state.get("date_preset"))
        new_start = max(min_day, max_day - timedelta(days=days - 1)) if days else current[0]
        st.session_state["date_range"] = (new_start, max_day)
    st.session_state["max_day_seen"] = max_day

    def _apply_preset():
        days = presets.get(st.session_state["date_preset"])
        start_day = max(min_day, max_day - timedelta(days=days - 1)) if days else min_day
        st.session_state["date_range"] = (start_day, max_day)

    def _clear_preset():
        # dragging the slider by hand no longer matches a preset
        st.session_state["date_preset"] = None

    if show_dates:
        st.pills("Last", list(presets), key="date_preset", on_change=_apply_preset,
                 help="Quick ranges ending on the latest day loaded")
        st.slider("Date range", min_value=min_day, max_value=max_day, step=timedelta(days=1),
                  format="DD MMM YYYY", key="date_range", on_change=_clear_preset)
    start, end = st.session_state["date_range"]

    if show_dims:
        # click to focus (e.g. only Japan), click more to combine, clear to see everything
        st.caption("Filters: nothing selected = everything.")
        for label, col in DIMENSIONS.items():
            st.pills(label, st.session_state["domains"][col], selection_mode="multi", key=f"filter_{col}")
    else:
        st.caption("This page isn't affected by the filters.")

    dims_filtered = daily
    if show_dims:
        for col in DIMENSIONS.values():
            chosen = st.session_state.get(f"filter_{col}")
            if chosen:
                dims_filtered = dims_filtered[dims_filtered[col].isin(chosen)]

st.session_state["daily_dims"] = dims_filtered
st.session_state["daily"] = dims_filtered[
    (dims_filtered["billed_at"].dt.date >= start) & (dims_filtered["billed_at"].dt.date <= end)]

if show_dims and (st.session_state["daily"] if show_dates else dims_filtered).empty:
    st.warning("No data for the selected filters.")
    st.stop()

pages.run()
