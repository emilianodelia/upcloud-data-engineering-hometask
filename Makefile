# Run `make help` for the list of commands.
# Which one to load data with:
#   make daily      every day: yesterday plus the 2 days before
#   make reconcile  the bucket decides: reloads files that arrived late, were never loaded, or were corrected
#   make backfill   you decide: reloads the START..END days you pass, whatever the reason

PYTHON  ?= python3
VENV    := .venv
PY      := $(VENV)/bin/python

# demo window: Dec 2025 plus the partial Jan 2026 (files exist up to 2026-01-11), so the
# dashboard shows a partial month and month-to-date vs same period last month
START   ?= 2025-12-01
END     ?= 2026-01-11
# day after END: a daily run that reloads the last days of the window (lookback)
EXEC_DATE ?= 2026-01-12
# replay: exec dates to simulate (one daily file "arrives" per step), seconds between steps, and
# the lookback per step (0 = only the new day, so each step is one ~265 MB file)
REPLAY_FIRST ?= 2026-01-06
REPLAY_LAST  ?= 2026-01-12
PAUSE        ?= 20
REPLAY_LOOKBACK ?= 0
# watch: seconds between daily runs
INTERVAL ?= 3600

.PHONY: demo setup backfill daily replay watch reconcile reconcile-dry publish dashboard docs clean help

help:  ## list the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

demo: setup backfill dashboard  ## first time here? installs, loads Dec 2025 - Jan 2026 and opens the dashboard

setup: $(VENV)/.installed  ## create .venv and install the pinned requirements

$(VENV)/.installed: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt
	@touch $@

backfill: setup  ## reload the days you choose: START..END (e.g. START=2025-12-05 END=2025-12-05 for one day)
	$(PY) scripts/run_pipeline.py --start $(START) --end $(END)

daily: setup  ## the normal daily run: loads yesterday and reloads the 2 days before (as of EXEC_DATE)
	$(PY) scripts/run_pipeline.py --exec-date $(EXEC_DATE)

replay: setup  ## demo only: pretend one new file arrives per step, REPLAY_FIRST..REPLAY_LAST
	$(PY) scripts/run_pipeline.py --replay $(REPLAY_FIRST) $(REPLAY_LAST) --pause $(PAUSE) --lookback $(REPLAY_LOOKBACK)

watch: setup  ## keep it running: a daily run every INTERVAL seconds + one reconcile per day (Ctrl+C to stop)
	$(PY) scripts/run_pipeline.py --watch --interval $(INTERVAL)

reconcile: setup  ## compare the bucket with the warehouse and reload late, missing or corrected files
	$(PY) scripts/run_pipeline.py --reconcile --end $(END)

reconcile-dry: setup  ## same as reconcile, but only show what it would reload
	$(PY) scripts/run_pipeline.py --reconcile --dry-run --end $(END)

publish: setup  ## refresh what the dashboard reads (serving.duckdb), without loading anything
	$(PY) scripts/run_pipeline.py --publish-only

dashboard: setup  ## start the dashboard only (Ctrl+C to stop)
	cd upcloud_billing_dwh && ../$(PY) -m streamlit run dashboard/app.py

docs: setup  ## open the dbt docs: model and column descriptions, lineage graph
	cd upcloud_billing_dwh && ../$(VENV)/bin/dbt docs generate --profiles-dir . && ../$(VENV)/bin/dbt docs serve --profiles-dir .

clean:  ## delete .venv and all local databases (start from scratch)
	rm -rf $(VENV) upcloud_billing_dwh/*.duckdb upcloud_billing_dwh/*.duckdb.wal upcloud_billing_dwh/*.duckdb.tmp upcloud_billing_dwh/pipeline.lock upcloud_billing_dwh/target
