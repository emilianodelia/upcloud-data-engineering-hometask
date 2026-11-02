# scripts/run_pipeline.py
"""
Pipeline runner: probes the daily billing files, loads the ones that exist with dbt, and
publishes a read-only snapshot for the dashboard.

Modes (see README, "Pipeline runner"):
    --exec-date D                 daily run: reloads the lookback window ending the day before D
    --start A --end B             backfill A..B
    --reconcile [--dry-run]       probe the whole loaded history, reload late, missing or changed files
    --watch [--interval S]        loop: a daily run every S seconds, plus one reconcile per calendar day
    --replay A B [--pause S]      simulate files arriving: a daily run for each exec date A..B
    --publish-only                rebuild serving.duckdb from the build database

Every successful run ends with a publish: what the dashboard reads is copied to serving.duckdb and
swapped in atomically, so the dashboard never reads the database dbt is writing, and only sees data
that passed the tests.
"""
import argparse, fcntl, json, os, shutil, subprocess, sys, time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import duckdb
import pandas as pd
import requests
import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent / "upcloud_billing_dwh"
DB_PATH = PROJECT_DIR / "billing.duckdb"        # build database: only this runner and dbt write it
SERVING_PATH = PROJECT_DIR / "serving.duckdb"   # published snapshot: the only file the dashboard reads
LOCK_PATH = PROJECT_DIR / "pipeline.lock"       # one pipeline run at a time (see run_lock)
# one source of truth for the bucket URL: the dbt var the models use to build file URLs
BASE_URL = yaml.safe_load((PROJECT_DIR / "dbt_project.yml").read_text())["vars"]["billing_base_url"]

SELECTOR = "@models/base/resource_usage_invoices"  # downstream models + all their parents
BASE_SCHEMA, BASE_TABLE = "base__resource_usage_invoices__intermediate", "build_base_resource_usage_invoices"

# pipeline metadata written by this script (not dbt), in an ops layer next to the dbt layers
OPS = "ops__ingestion"
MANIFEST = f"{OPS}.billing_file_manifest"   # one row per file date: what the bucket has, what was loaded
RECONCILE_LOG = f"{OPS}.reconcile_log"      # one row per reconcile run: what it found and reloaded
SNAPSHOT = "ops__serving.snapshot"          # one row: when serving.duckdb was published, data through

# copied to serving.duckdb on publish: everything the dashboard reads, nothing else
SERVED_TABLES = [
    "marts__domain_finance.report_billing_daily",
    "marts__domain_client_ops.report_client_usage_daily",
    MANIFEST,
    RECONCILE_LOG,
]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


@contextmanager
def run_lock():
    """One pipeline run at a time. Two overlapping runs would fight over DuckDB's single writer
    lock, and the loser fails mid-load. The OS releases the lock if the process dies, so a crashed
    run never leaves it stuck."""
    with open(LOCK_PATH, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another pipeline run is in progress (pipeline.lock): try again when it ends.")
        f.write(str(os.getpid()))
        f.flush()
        yield


def date_range(start, end):
    return [start + timedelta(n) for n in range((end - start).days + 1)]


# ---------- probing the bucket ----------

def url_for(d):
    return f"{BASE_URL}/year={d:%Y}/month={d:%m}/day={d:%d}/billing.csv"


def probe(d):
    """HEAD one daily file. The ETag identifies the file's content, so a corrected file shows up
    as a new ETag on the same date. status None = network error after 3 tries."""
    row = {"file_date": d, "status": None, "etag": None, "last_modified": None, "content_length": None}
    for _ in range(3):  # retry transient network errors
        try:
            r = requests.head(url_for(d), timeout=10)
        except requests.RequestException:
            continue
        row["status"] = r.status_code
        if r.status_code == 200:
            h = r.headers
            row["etag"] = h.get("ETag", "").strip('"') or None
            row["last_modified"] = parsedate_to_datetime(h["Last-Modified"]).replace(tzinfo=None) \
                if "Last-Modified" in h else None
            row["content_length"] = int(h["Content-Length"]) if "Content-Length" in h else None
        return row
    return row


def probe_days(days):
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(probe, days))
    # Only a 404 counts as "file not there". Anything else is an error, not a gap.
    unexpected = [(str(r["file_date"]), r["status"]) for r in results if r["status"] not in (200, 404)]
    if unexpected:
        raise SystemExit(f"Unexpected responses, aborting: {unexpected[:10]}")
    return results


# ---------- ops tables ----------

def ensure_ops_tables(con):
    con.execute(f"create schema if not exists {OPS}")
    con.execute(f"""create table if not exists {MANIFEST} (
        file_date date,           -- the billing day the file holds
        status integer,           -- last HEAD status: 200 found, 404 missing
        etag varchar,             -- content hash the bucket reports now
        last_modified timestamp,  -- upload time the bucket reports now
        content_length bigint,    -- size in bytes
        first_seen_at timestamp,  -- first probe that found the file (200)
        last_checked_at timestamp,
        loaded_etag varchar,      -- ETag of the version loaded into the warehouse (null = never loaded)
        loaded_at timestamp       -- when that version was loaded
    )""")
    con.execute(f"""create table if not exists {RECONCILE_LOG} (
        checked_at timestamp, range_start date, range_end date, files_found integer,
        late integer, holes integer, changed integer, disappeared integer,
        baseline_adopted integer, days_loaded integer, dry_run boolean
    )""")
    # the old probe log is replaced by the manifest
    con.execute(f"drop table if exists {OPS}.billing_file_probe")


def update_manifest(con, results):
    """Upsert the probe results: refresh what the bucket reports, keep what was loaded."""
    probes = pd.DataFrame(results)
    probes["checked_at"] = datetime.now()
    con.register("probes", probes)
    con.execute(f"""
        update {MANIFEST} m set
            status = p.status, etag = p.etag, last_modified = p.last_modified,
            content_length = p.content_length, last_checked_at = p.checked_at,
            first_seen_at = coalesce(m.first_seen_at, case when p.status = 200 then p.checked_at end)
        from probes p where m.file_date = p.file_date::date""")
    con.execute(f"""
        insert into {MANIFEST}
        select p.file_date::date, p.status, p.etag, p.last_modified, p.content_length,
               case when p.status = 200 then p.checked_at end, p.checked_at, null, null
        from probes p
        where not exists (select 1 from {MANIFEST} m where m.file_date = p.file_date::date)""")
    con.unregister("probes")


def mark_loaded(con, dates):
    """The loaded version of each day is the ETag just probed (adopted as-is for baselines)."""
    if dates:
        con.execute(f"update {MANIFEST} set loaded_etag = etag, loaded_at = ? "
                    f"where file_date in (select unnest(?::date[]))", [datetime.now(), list(dates)])


def loaded_partitions(con):
    """Days present in the incremental base table (empty if it is not built yet)."""
    exists = con.execute("select count(*) from information_schema.tables "
                         "where table_schema = ? and table_name = ?", [BASE_SCHEMA, BASE_TABLE]).fetchone()[0]
    if not exists:
        return set()
    return {r[0] for r in con.execute(f"select distinct partition_date from {BASE_SCHEMA}.{BASE_TABLE}").fetchall()}


# ---------- dbt and publish ----------

def load(dates, full_refresh=False):
    """Load exactly these days (delete+insert on partition_date), rebuild and test everything
    downstream, record the loaded versions, and publish. Raises if dbt fails: nothing is published."""
    dates = sorted(d.isoformat() for d in dates)
    vars_ = {
        # start/end scope the window-filtered tests (macros/get_where_subquery.sql) to min..max of the batch
        "billing_start_date": dates[0],
        "billing_end_date": dates[-1],
        "billing_available_dates": dates,
    }
    # use the dbt installed next to this Python (e.g. .venv/bin/dbt), so the runner works
    # from a virtualenv without activating it; fall back to whatever dbt is on PATH
    venv_dbt = next((p for p in (Path(sys.executable).parent / n for n in ("dbt", "dbt.exe")) if p.exists()), None)
    dbt = str(venv_dbt) if venv_dbt else shutil.which("dbt") or "dbt"
    cmd = [dbt, "build", "-s", SELECTOR, "--profiles-dir", str(PROJECT_DIR), "--vars", json.dumps(vars_)]
    if full_refresh:
        cmd.append("--full-refresh")
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)
    with duckdb.connect(str(DB_PATH)) as con:
        mark_loaded(con, dates)
    publish()


def publish():
    """Copy what the dashboard reads into a fresh file and swap it in with one atomic rename.
    Runs only after dbt build (models + tests) succeeded, so a failed run never reaches the dashboard:
    it keeps showing the last good snapshot. Readers holding the old file are unaffected."""
    tmp = SERVING_PATH.with_name(SERVING_PATH.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        con.execute(f"attach '{DB_PATH}' as build (read_only)")
        for table in SERVED_TABLES:
            con.execute(f"create schema if not exists {table.split('.')[0]}")
            con.execute(f"create table {table} as select * from build.{table}")
        con.execute(f"create schema if not exists {SNAPSHOT.split('.')[0]}")
        con.execute(f"""create table {SNAPSHOT} as select
            now()::timestamp as published_at,
            (select max(billed_at) from marts__domain_finance.report_billing_daily) as data_through""")
        con.execute("detach build")
        con.execute("checkpoint")  # everything in the main file, no .wal left behind
    os.replace(tmp, SERVING_PATH)  # atomic rename on the same filesystem
    log(f"published {SERVING_PATH.name}")


# ---------- run modes ----------

def run_window(start, end, full_refresh=False):
    """Daily run or backfill: probe start..end, load the files that exist, publish."""
    days = date_range(start, end)
    results = probe_days(days)
    available = [r["file_date"] for r in results if r["status"] == 200]
    log(f"window {start}..{end}: {len(available)} of {len(days)} files available, "
        f"{len(days) - len(available)} missing")

    with duckdb.connect(str(DB_PATH)) as con:
        ensure_ops_tables(con)
        update_manifest(con, results)
        # Days between the last loaded partition and this window are never picked up by later
        # daily runs: flag them. Late files and holes anywhere in the history are found by --reconcile.
        if not full_refresh:
            loaded = loaded_partitions(con)
            last_loaded = max(loaded) if loaded else None
            if last_loaded and start > last_loaded + timedelta(days=1):
                log(f"WARNING: {last_loaded + timedelta(days=1)} to {start - timedelta(days=1)} not loaded "
                    f"and not covered by this window. Run --reconcile, or backfill with --start/--end.")
    # connection closed here: DuckDB allows one writer, and dbt needs the file

    if not available:
        raise SystemExit(f"No billing files available in {start}..{end}: nothing to load.")
    load(available, full_refresh)


def run_reconcile(start, end, dry_run=False):
    """Compare the bucket with the warehouse over start..end (default: from the first day ever loaded)
    and reload the days that differ:
        late         file exists now, was missing (404) on an earlier probe, never loaded
        hole         file exists, never loaded, not seen missing before (e.g. a skipped backfill)
        changed      file was loaded, and its ETag has changed since (a corrected file)
        disappeared  file was loaded, and is now 404: kept and reported, never deleted (append-only source)
    Days loaded before the manifest existed have no loaded ETag: the current one is adopted as the
    baseline (baseline_adopted), so the first reconcile does not reload the whole history.
    --dry-run reports only: it writes nothing but the reconcile log."""
    with duckdb.connect(str(DB_PATH)) as con:
        ensure_ops_tables(con)
        loaded = loaded_partitions(con)
        before = con.execute(f"select file_date, status, loaded_etag from {MANIFEST}").fetchall()
    before = {d: (status, loaded_etag) for d, status, loaded_etag in before}
    # history starts at the first day ever loaded: the warehouse's first day, or the manifest's,
    # so a day lost from the start of the warehouse is still inside the range and found as a hole
    ever_loaded = loaded | {d for d, (_, loaded_etag) in before.items() if loaded_etag is not None}
    if not ever_loaded and start is None:
        raise SystemExit("Nothing loaded yet: run a backfill first (--start/--end).")
    start = start or min(ever_loaded)
    log(f"reconcile {start}..{end}: probing {(end - start).days + 1} files")
    results = probe_days(date_range(start, end))

    late, holes, changed, disappeared, baseline = [], [], [], [], []
    for r in results:
        d, status, etag = r["file_date"], r["status"], r["etag"]
        prev_status, loaded_etag = before.get(d, (None, None))
        if status == 200 and d not in loaded:
            (late if prev_status == 404 else holes).append(d)
        elif status == 200 and loaded_etag is None:
            baseline.append(d)
        elif status == 200 and loaded_etag != etag:
            changed.append(d)
        elif status == 404 and d in loaded:
            disappeared.append(d)

    to_load = sorted(late + holes + changed)
    found = sum(r["status"] == 200 for r in results)
    log(f"found {found} files: late {len(late)}, holes {len(holes)}, changed {len(changed)}, "
        f"disappeared {len(disappeared)}, baseline adopted {len(baseline)}")
    for label, ds in (("late", late), ("holes", holes), ("changed", changed), ("disappeared (kept)", disappeared)):
        if ds:
            log(f"  {label}: {', '.join(map(str, ds[:15]))}{' ...' if len(ds) > 15 else ''}")

    with duckdb.connect(str(DB_PATH)) as con:
        if not dry_run:
            update_manifest(con, results)
            mark_loaded(con, baseline)
        con.execute(f"insert into {RECONCILE_LOG} values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [datetime.now(), start, end, found, len(late), len(holes), len(changed),
                     len(disappeared), len(baseline), 0 if dry_run else len(to_load), dry_run])

    if dry_run:
        log(f"dry run: would reload {len(to_load)} days, nothing written")
    elif to_load:
        log(f"reloading {len(to_load)} days")
        load(to_load)
    else:
        log("warehouse matches the bucket: nothing to reload")
        publish()  # the reconcile log changed: show it on the dashboard


def run_daily(exec_date, lookback):
    end = exec_date - timedelta(days=1)
    run_window(end - timedelta(days=lookback), end)


def run_watch(interval, lookback):
    """Long-running scheduler for one machine: a daily run every `interval` seconds, plus one
    reconcile per calendar day. A failed tick is logged and retried on the next one; the dashboard
    keeps the last published snapshot meanwhile. In production: cron or an orchestrator."""
    last_reconcile = None
    while True:
        today = date.today()
        try:
            with run_lock():
                run_daily(today, lookback)
        except (Exception, SystemExit) as e:
            log(f"daily run failed, retrying next tick: {e}")
        if last_reconcile != today:
            try:
                with run_lock():
                    run_reconcile(None, today - timedelta(days=1))
                last_reconcile = today
            except (Exception, SystemExit) as e:
                log(f"reconcile failed, retrying next tick: {e}")
        log(f"next run in {interval}s")
        time.sleep(interval)


def run_replay(first, last, lookback, pause):
    """Simulated clock: the source is static, so replay it as if one file arrived per day.
    Each step is a normal daily run "as of" that exec date and ends with a publish, so an open
    dashboard picks up each new day as it lands."""
    for exec_date in date_range(first, last):
        log(f"--- replay: exec date {exec_date}")
        with run_lock():  # per step, so a manual run can slip in between steps
            run_daily(exec_date, lookback)
        if exec_date != last:
            time.sleep(pause)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exec-date", type=date.fromisoformat, help="daily run as of this date (default: today)")
    p.add_argument("--lookback", type=int, default=2, help="extra days before exec date - 1 to reload")
    p.add_argument("--start", type=date.fromisoformat, help="backfill / reconcile range start")
    p.add_argument("--end", type=date.fromisoformat, help="backfill / reconcile range end")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--reconcile", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="with --reconcile: report, load nothing")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval", type=int, default=3600, help="with --watch: seconds between runs")
    p.add_argument("--replay", nargs=2, type=date.fromisoformat, metavar=("FIRST", "LAST"),
                   help="exec dates to replay, one daily run each")
    p.add_argument("--pause", type=int, default=20, help="with --replay: seconds between days")
    p.add_argument("--publish-only", action="store_true")
    a = p.parse_args()

    # The base model only reads the window's files, even on a full refresh: refreshing
    # with the default 3-day window would drop the table and wipe the rest of the history.
    if a.full_refresh and not a.start:
        raise SystemExit("--full-refresh rebuilds the base table from the window only. "
                         "Pass --start (and --end) covering the full history to reload.")

    end = a.end or (a.exec_date or date.today()) - timedelta(days=1)

    if a.watch:
        run_watch(a.interval, a.lookback)
    elif a.replay:
        run_replay(a.replay[0], a.replay[1], a.lookback, a.pause)
    else:
        with run_lock():
            if a.publish_only:
                publish()
            elif a.reconcile:
                run_reconcile(a.start, end, a.dry_run)
            else:
                run_window(a.start or end - timedelta(days=a.lookback), end, a.full_refresh)


if __name__ == "__main__":
    main()
