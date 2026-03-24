#!/usr/bin/env python3
"""
db_updater.py — Persist last-7-days time series for STATIONS into SQLite.

- Imports STATIONS and data-fetch functions from your existing flask_app.py
- Inserts readings with deduplication (PRIMARY KEY on station_key + ts_utc)
- Keeps only the last 7 days
- Can run once (for cron) or loop every 15 minutes

Usage:
  python db_updater.py --db ../docs/data/timeseries.sqlite --once --days 7 --log-file test_update.log
  python db_updater.py --db ../docs/data/timeseries.sqlite --loop --days 7
  python db_updater.py --db ../docs/data/timeseries.sqlite --backfill-days 7 --once

Author: you
"""

import argparse
import logging
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

# Add current directory to sys.path to ensure we can import local modules
sys.path.append(os.getcwd())

# --- import from your existing Flask app so behavior stays consistent ---
# (This relies on flask_app.py being in the same directory)
try:
    from flask_app import STATIONS, get_station_data  # noqa: F401
except Exception as e:
    raise SystemExit(
        f"Could not import STATIONS/get_station_data from flask_app.py: {e}\n"
        "Make sure db_updater.py is in the same directory as flask_app.py"
    )
# STATIONS definition and get_station_data are taken from your file.  # noqa: E402
# (Shoothill handling and EA logic remain identical to the Flask app.)  # noqa: E402
# ref: flask_app.py 


DEFAULT_DB_PATH = os.environ.get("TS_DB_PATH", "../docs/data/timeseries.sqlite")
RETENTION_DAYS = int(os.environ.get("TS_RETENTION_DAYS", "7"))   # keep last 7 days
FETCH_WINDOW_DAYS = int(os.environ.get("TS_FETCH_WINDOW_DAYS", "7"))  # refetch this window each run
MIN_FETCH_SECONDS = 900  # always fetch at least 15 mins to catch the very latest readings


def utc_now():
    return datetime.now(tz=timezone.utc)


def iso_to_epoch_seconds(iso_str: str) -> int:
    # Robust ISO8601 → epoch seconds (UTC)
    # (Your get_station_data already returns ISO timestamps; they may have TZ offsets.)
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return int(dt.timestamp())


def ensure_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            station_key TEXT NOT NULL,
            station_id  TEXT NOT NULL,
            source      TEXT NOT NULL,
            ts_utc      INTEGER NOT NULL,     -- epoch seconds (UTC)
            value       REAL NOT NULL,
            PRIMARY KEY (station_key, ts_utc)
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_readings_station_ts ON readings(station_key, ts_utc);"
    )
    conn.commit()


def save_readings(conn: sqlite3.Connection, station_key: str, station_meta: dict, readings: list[dict]):
    """
    readings: list of {"dateTime": ISO8601, "value": float}
    """
    if not readings:
        return 0

    rows = []
    for r in readings:
        try:
            ts = iso_to_epoch_seconds(r["dateTime"])
            val = float(r["value"])
            rows.append((station_key, station_meta["id"], station_meta["source"], ts, val))
        except Exception:
            # Skip malformed rows
            continue

    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR IGNORE INTO readings (station_key, station_id, source, ts_utc, value)
        VALUES (?, ?, ?, ?, ?);
        """,
        rows
    )
    conn.commit()
    return cur.rowcount  # number of *attempted* inserts (ignored duplicates won't count)


def latest_stored_ts(conn: sqlite3.Connection, station_key: str) -> int | None:
    """Return the most recent ts_utc (epoch seconds) stored for *station_key*, or None."""
    cur = conn.cursor()
    cur.execute(
        "SELECT MAX(ts_utc) FROM readings WHERE station_key = ?;",
        (station_key,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def prune_old(conn: sqlite3.Connection, retention_days: int):
    cutoff = utc_now() - timedelta(days=retention_days)
    cutoff_epoch = int(cutoff.timestamp())
    cur = conn.cursor()
    cur.execute("DELETE FROM readings WHERE ts_utc < ?;", (cutoff_epoch,))
    deleted = cur.rowcount
    conn.commit()
    return deleted




def update_once(conn: sqlite3.Connection, fetch_days: int, retention_days: int) -> dict:
    """
    Fetch only the data not yet stored for each station, then prune old data.

    For each station the function checks the most recent timestamp already in
    the database and requests only the window between that point and now.
    If no data exists yet the full *fetch_days* window is requested.
    """
    total_inserts = 0
    per_station = {}
    now_epoch = int(utc_now().timestamp())

    # We reuse your Flask app's "get_station_data" which handles EA and Shoothill uniformly.
    # This returns: {"station": {...}, "readings": [ {dateTime, value}, ...], "stats": {...}}
    # ref: flask_app.py
    for station_key, meta in STATIONS.items():
        try:
            latest_ts = latest_stored_ts(conn, station_key)
            if latest_ts is None:
                # No data yet — fetch the full requested window.
                days_to_fetch = fetch_days
                logging.info(f"{station_key}: No data in DB, fetching {fetch_days} days")
            else:
                gap_seconds = now_epoch - latest_ts
                logging.info(f"{station_key}: gap_seconds {gap_seconds}s")
                if gap_seconds < MIN_FETCH_SECONDS:
                    logging.info(
                        f"{station_key}: already up-to-date "
                        f"(latest reading {gap_seconds}s ago), skipping fetch"
                    )
                    per_station[station_key] = 0
                    continue
                # Round up to the nearest whole day (minimum 1) so the API window
                # covers the entire gap.  Cap at fetch_days so we never over-fetch.
                days_to_fetch = min(fetch_days, max(1, math.ceil(gap_seconds / 86400)))

            resp = get_station_data(station_key, ndays=days_to_fetch)
            readings = resp.get("readings", [])
            n = save_readings(conn, station_key, meta, readings)
            per_station[station_key] = n
            total_inserts += n
            logging.info(f"{station_key}: {n} new readings (window={days_to_fetch}d)")
        except Exception as e:
            logging.exception(f"Error processing station '{station_key}': {e}")
            per_station[station_key] = 0

    deleted = prune_old(conn, retention_days)
    logging.info(f"Pruned {deleted} old rows (> {RETENTION_DAYS} days)")
    return {"inserted": total_inserts, "deleted": deleted, "per_station": per_station}


def sleep_until_next_quarter():
    """
    Sleep until the next 15-minute boundary (00, 15, 30, 45).
    """
    now = time.time()
    next_q = math.ceil(now / 900) * 900  # 900s = 15 minutes
    delay = max(0, next_q - now)
    time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description="Persist last-7-days time series for STATIONS into SQLite.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database (default: ./timeseries.sqlite)")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS, help="Retention window in days (default: 7)")
    parser.add_argument("--fetch-days", type=int, default=FETCH_WINDOW_DAYS,
                        help="How many recent days to (re)fetch each run (default: 7)")
    parser.add_argument("--once", action="store_true", help="Run once then exit")
    parser.add_argument("--loop", action="store_true", help="Run forever, aligning to 15-minute boundaries")
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="Optional one-off backfill window (days) to fetch before normal run")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    parser.add_argument("--log-file", default=None, help="Optional log file path (default: log to console)")
    args = parser.parse_args()

    # make retention & fetch tunable via CLI
    log_config = {
        "level": getattr(logging, args.log_level.upper(), logging.INFO),
        "format": "%(asctime)s %(levelname)s %(message)s",
        "force": True  # Override any existing logging configuration
    }
    if args.log_file:
        log_config["filename"] = args.log_file
    logging.basicConfig(**log_config)

    # connect to DB
    conn = sqlite3.connect(args.db, timeout=30, isolation_level=None)  # autocommit
    ensure_schema(conn)

    # optional backfill (idempotent)
    if args.backfill_days and args.backfill_days > 0:
        logging.info(f"Backfill: fetching last {args.backfill_days} day(s)")
        update_once(conn, fetch_days=args.backfill_days, retention_days=args.days)

    # run once or loop
    if args.once and not args.loop:
        update_once(conn, fetch_days=args.fetch_days, retention_days=args.days)
        return

    if args.loop:
        # align to quarter and keep going
        logging.info("Entering loop mode; aligning to 15-minute boundaries.")
        # Do an immediate update on start:
        update_once(conn, fetch_days=args.fetch_days, retention_days=args.days)
        while True:
            sleep_until_next_quarter()
            update_once(conn, fetch_days=args.fetch_days,  retention_days=args.days)
    else:
        # default if no flags: run once
        update_once(conn, fetch_days=args.fetch_days, retention_days=args.days)


if __name__ == "__main__":
    main()
