# dashboard/app.py
# run from upcloud_billing_dwh/ with the same Python as dbt (DuckDB 2.x reads the file):
#   python3 -m streamlit run dashboard/app.py
# reads serving.duckdb, the snapshot the pipeline publishes after each successful run, so the
# pipeline can run while the app is open: new data shows up within ~30s (see _watch_snapshot)
import streamlit as st

from common import SERVING, q, snapshot_version

st.set_page_config(page_title="Billing metrics", layout="wide")


@st.fragment(run_every=30)
def _watch_snapshot():
    # polls the snapshot file: when the pipeline publishes a new one, rerun the whole app so
    # every page reads the new data (queries are cached per snapshot, see common.q)
    version = snapshot_version()
    seen = st.session_state.setdefault("snapshot_version", version)
    if version != seen:
        st.session_state["snapshot_version"] = version
        st.rerun(scope="app")
    snap = q(f"select published_at, data_through from {SERVING}.snapshot").iloc[0]
    st.caption(f"**Data through {snap.data_through:%d %b %Y}** · published {snap.published_at:%d %b %H:%M}  \n"
               "Loaded once a day (EOD): the latest day is yesterday, no intraday data. "
               "Refreshes by itself when the pipeline publishes.")


pages = st.navigation([
    st.Page("views/credit_daily.py", title="Credit usage, daily", icon=":material/today:", default=True),
    st.Page("views/credit_history.py", title="Credit usage, history", icon=":material/history:"),
    st.Page("views/pipeline_health.py", title="Pipeline health", icon=":material/monitor_heart:"),
])
with st.sidebar:
    _watch_snapshot()
pages.run()
