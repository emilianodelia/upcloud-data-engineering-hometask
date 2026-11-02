import altair as alt
import pandas as pd
import streamlit as st

from common import MARTS, OPS, q, series, table_exists

st.title("Data health")
st.caption("Pipeline checks: which daily billing files exist and what was loaded. "
           "Not affected by the sidebar filters.")

loaded = q("select billed_at, sum(total_transactions) as transactions "
           f"from {MARTS}.report_billing_daily group by billed_at order by billed_at")
loaded["billed_at"] = pd.to_datetime(loaded["billed_at"])

calendar = pd.date_range(loaded["billed_at"].min(), loaded["billed_at"].max(), freq="D")
missing_days = calendar.difference(loaded["billed_at"])

c1, c2, c3 = st.columns(3)
c1.metric("Last day loaded", f"{loaded['billed_at'].max():%d %b %Y}", border=True)
c2.metric("Days loaded", len(loaded), border=True)
c3.metric("Gaps inside the loaded range", len(missing_days), border=True)
if len(missing_days):
    st.warning("Missing days: " + ", ".join(f"{d:%Y-%m-%d}" for d in missing_days)
               + ". Run make reconcile to load them (or backfill with --start/--end).")

st.subheader("Transactions loaded per day")
st.altair_chart(
    alt.Chart(loaded).mark_bar(color=series()[0], cornerRadiusEnd=4).encode(
        x=alt.X("billed_at:T", title=None, axis=alt.Axis(format="%d %b", grid=False)),
        y=alt.Y("transactions:Q", title="Transactions", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("billed_at:T", title="Date", format="%d %b %Y"),
                 alt.Tooltip("transactions:Q", title="Transactions", format=",")],
    ).properties(height=260),
    width="stretch",
)

st.subheader("Last reconcile")
st.caption("A reconcile probes every file in the loaded history and reloads the days that differ "
           "from the bucket (run_pipeline.py --reconcile, and once a day in --watch).")
if table_exists(OPS, "reconcile_log"):
    rec = q(f"select * from {OPS}.reconcile_log order by checked_at desc")
    if rec.empty:
        st.info("No reconcile has run yet: make reconcile.")
    else:
        last = rec.iloc[0]
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Late files", int(last["late"]), border=True,
                  help="Missing on an earlier probe, found now, then loaded")
        r2.metric("Holes", int(last["holes"]), border=True,
                  help="In the bucket but never loaded (e.g. a skipped backfill)")
        r3.metric("Changed files", int(last["changed"]), border=True,
                  help="ETag differs from the version loaded: the day is reloaded")
        r4.metric("Disappeared", int(last["disappeared"]), border=True,
                  help="Loaded before, now missing in the bucket: data kept, reported here")
        r5.metric("Days reloaded", int(last["days_loaded"]), border=True)
        st.caption(f"Checked {last['checked_at']:%d %b %Y %H:%M} over {last['range_start']:%d %b %Y} – "
                   f"{last['range_end']:%d %b %Y}{' (dry run)' if last['dry_run'] else ''}.")
        with st.expander("Reconcile history"):
            st.dataframe(rec, hide_index=True, width="stretch")

st.subheader("File manifest")
if table_exists(OPS, "billing_file_manifest"):
    manifest = q("select file_date, status, etag, loaded_etag, last_modified, content_length, "
                 "first_seen_at, last_checked_at, loaded_at "
                 f"from {OPS}.billing_file_manifest order by file_date desc")
    manifest.insert(1, "result", manifest["status"].map({200: "Found", 404: "Missing"}).fillna("Error"))
    manifest.insert(2, "loaded", manifest["loaded_etag"].notna()
                    .map({True: "Loaded", False: "Not loaded"})
                    .where(manifest["loaded_etag"].isna() | (manifest["loaded_etag"] == manifest["etag"]),
                           "Stale (file changed)"))
    st.caption(f"{(manifest['status'] == 200).sum()} found, {(manifest['status'] == 404).sum()} missing. "
               "One row per daily file, from the HEAD checks run_pipeline.py makes: the ETag the bucket "
               "reports now, and the one loaded into the warehouse.")
    st.dataframe(manifest, hide_index=True, width="stretch")
else:
    st.info("No file manifest yet: it's written by scripts/run_pipeline.py.")
