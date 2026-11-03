import altair as alt
import streamlit as st

from common import BLUE, DATA_OPS, count, q

st.title("Pipeline health")
st.caption("One row per daily file the pipeline checked: did it exist, was it loaded, how many rows came in. "
           "Days never checked show up after make reconcile, which probes every day of the history.")

summary = q(f"select * from {DATA_OPS}.report_pipeline_health_summary").iloc[0]
df = q(f"select * from {DATA_OPS}.report_pipeline_health_daily order by file_date")

c = st.columns(4)
c[0].metric("Last day loaded", f"{summary.last_day_loaded:%d %b %Y}" if summary.files_loaded else "–", border=True)
c[1].metric("Files loaded", count(summary.files_loaded), border=True)
c[2].metric("Files missing in bucket", count(summary.files_missing), border=True)
c[3].metric("Changed since loaded", count(summary.files_changed_since_loaded), border=True,
            help="make reconcile reloads them")

st.subheader("Rows loaded per day")
st.caption("A drop or a gap means a file is late, missing or truncated.")
st.altair_chart(alt.Chart(df).mark_bar(color=BLUE, cornerRadiusEnd=3, width={"band": 0.8}).encode(
    x=alt.X("yearmonthdate(file_date):T", title=None, axis=alt.Axis(format="%d %b", grid=False)),
    y=alt.Y("rows_loaded:Q", title="Rows", axis=alt.Axis(format="~s")),
    tooltip=[alt.Tooltip("file_date:T", title="Day", format="%d %b %Y"),
             alt.Tooltip("file_status:N", title="File"), alt.Tooltip("rows_loaded:Q", title="Rows", format=",")],
).properties(height=280), width="stretch")

st.subheader("Per file")
st.dataframe(df.iloc[::-1], hide_index=True, width="stretch",
             column_config={"file_date": st.column_config.DateColumn("File date", format="DD MMM YYYY"),
                            "file_status": "Status", "is_loaded": "Loaded", "is_stale": "Changed since loaded",
                            "loaded_at": st.column_config.DatetimeColumn("Loaded at", format="DD MMM YYYY HH:mm"),
                            "rows_loaded": st.column_config.NumberColumn("Rows loaded", format="%d")})
