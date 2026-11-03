# dashboard/common.py
# Data access, filters and display formatting only: every metric is a column of a dbt model
# (models/marts/domain_finance/credit_usage, domain_client_ops, domain_data_ops/pipeline_health).
from pathlib import Path

import altair as alt
import duckdb
import streamlit as st

# The dashboard reads the published snapshot, never the build database dbt writes: the runner
# swaps serving.duckdb in atomically after a run passes its tests (scripts/run_pipeline.py, publish),
# so the pipeline can run while the app is open. Resolved relative to this file.
DB_PATH = Path(__file__).resolve().parent.parent / "serving.duckdb"
# schemas derived from the folder path (macros/generate_schema_name.sql)
FINANCE = "marts__domain_finance"
CLIENT_OPS = "marts__domain_client_ops"
DATA_OPS = "marts__domain_data_ops"
SERVING = "ops__serving"  # snapshot: published_at, data_through (scripts/run_pipeline.py)

DIMENSIONS = {"Country": "country", "Resource type": "resource_type",
              "Service tier": "service_tier", "Operation type": "operation_type"}
BLUE, RED = "#2a78d6", "#e34948"


def snapshot_version():
    """Changes every time the runner publishes a new serving.duckdb (new file, new mtime)."""
    try:
        return DB_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return None


@st.cache_data(show_spinner=False, max_entries=256)
def _query(sql, params, version):
    # `version` is part of the cache key: a new snapshot invalidates every cached query at once
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql, list(params)).df()


def q(sql, params=()):
    version = snapshot_version()
    if version is None:
        st.warning("No published data yet: run the pipeline first (make backfill).")
        st.stop()
    try:
        return _query(sql, tuple(params), version)
    except duckdb.IOException as e:
        st.error(f"Could not open serving.duckdb.\n\n{e}")
        st.stop()
    except duckdb.CatalogException as e:
        st.error(f"A table is missing. Run the pipeline (or make publish) first.\n\n{e}")
        st.stop()


def slice_filters(table):
    """One select box per dimension ('All' = not sliced). Returns the where clause and its values:
    the models already hold a row for every combination, so filtering is all the dashboard does."""
    where, params = [], []
    for col, (label, dim) in zip(st.columns(len(DIMENSIONS)), DIMENSIONS.items()):
        options = q(f"select distinct {dim} from {table} where {dim} <> 'All' order by 1")[dim].tolist()
        where.append(f"{dim} = ?")
        params.append(col.selectbox(label, ["All"] + options, key=f"filter_{dim}"))
    return " and ".join(where), params


# ---------- display formatting ----------

def credits(v):
    # always in millions, one unit everywhere (1 billion shows as 1,000.0M). Credits are not money.
    return f"{v / 1e6:,.1f}M cr"


def count(v):
    return f"{v:,.0f}"


def rate(v):
    return f"{v:.2%}"


def millions_axis(title):
    return alt.Axis(title=title, labelExpr="format(datum.value / 1e6, ',.0f') + 'M'")
