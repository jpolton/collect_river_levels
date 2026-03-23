#!/usr/bin/env python3
"""
check_gaps.py - Detects gaps in timeseries JSON data files.

For each JSON file in docs/data/, this script:
  - Auto-detects whether the data is hourly or 15-minute interval.
  - Reports any gaps larger than the detected interval.
  - Summarises the number of gaps and total missing timesteps per file.

Usage:

    python scripts/check_gaps.py --data-dir path/to/data
    python scripts/check_gaps.py --file docs/data/chester.json

    # Log to console (default)
    python scripts/check_gaps.py
    
    # Log to file
    python scripts/check_gaps.py --log-file docs/data/test_update.log

    # Log to file, single station
    python scripts/check_gaps.py --file docs/data/chester.json --log-file docs/data/test_update.log

"""

import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone


def load_timestamps(filepath: Path) -> list[int]:
    """Load and return sorted unix timestamps from a JSON data file."""
    with open(filepath) as f:
        data = json.load(f)
    records = data.get("data", [])
    return sorted(r["ts_utc"] for r in records if "ts_utc" in r)


def detect_interval(timestamps: list[int]) -> int | None:
    """
    Auto-detect the dominant interval (in seconds) from consecutive differences.
    Returns the mode of the differences, or None if fewer than 2 points.
    """
    if len(timestamps) < 2:
        return None
    diffs = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    # Use the most common difference as the expected interval
    return max(set(diffs), key=diffs.count)


def find_gaps(timestamps: list[int], interval: int) -> list[dict]:
    """
    Find all gaps in the timeseries larger than `interval` seconds.

    Returns a list of dicts with:
        - gap_start: datetime of the last seen timestamp before the gap
        - gap_end:   datetime of the first timestamp after the gap
        - missing_steps: number of missing timesteps in the gap
        - gap_seconds: total gap duration in seconds
    """
    gaps = []
    for i in range(len(timestamps) - 1):
        diff = timestamps[i + 1] - timestamps[i]
        if diff > interval:
            missing = (diff // interval) - 1
            gaps.append(
                {
                    "gap_start": datetime.fromtimestamp(
                        timestamps[i], tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "gap_end": datetime.fromtimestamp(
                        timestamps[i + 1], tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "missing_steps": int(missing),
                    "gap_seconds": diff,
                }
            )
    return gaps


def interval_label(seconds: int) -> str:
    if seconds == 3600:
        return "hourly (3600 s)"
    if seconds == 900:
        return "15-minute (900 s)"
    minutes = seconds // 60
    return f"{minutes}-minute ({seconds} s)"


def check_file(filepath: Path) -> None:
    logging.info("=" * 60)
    logging.info(f"File: {filepath.name}")
    logging.info("=" * 60)

    try:
        timestamps = load_timestamps(filepath)
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"  ERROR reading file: {e}")
        return

    if len(timestamps) < 2:
        logging.info("  Not enough data points to check for gaps.")
        return

    start_dt = datetime.fromtimestamp(timestamps[0], tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    end_dt = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    logging.info(f"  Records  : {len(timestamps)}")
    logging.info(f"  Range    : {start_dt}  ->  {end_dt}")

    interval = detect_interval(timestamps)
    if interval is None:
        logging.info("  Not enough data points to determine interval.")
        return
    logging.info(f"  Interval : {interval_label(interval)}")

    gaps = find_gaps(timestamps, interval)

    if not gaps:
        logging.info("  No gaps detected.")
        return

    total_missing = sum(g["missing_steps"] for g in gaps)
    logging.info(f"  {len(gaps)} gap(s) found -- {total_missing} missing timestep(s) total")

    now = datetime.now(tz=timezone.utc)
    first_gap_start_ts = timestamps[
        next(
            i
            for i in range(len(timestamps) - 1)
            if timestamps[i + 1] - timestamps[i] > interval
        )
    ]
    first_gap_start_dt = datetime.fromtimestamp(first_gap_start_ts, tz=timezone.utc)
    days_since = (now - first_gap_start_dt).total_seconds() / 86400
    logging.info(
        f"  First gap started {days_since:.1f} days ago"
        f" ({first_gap_start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')})"
    )

    for i, gap in enumerate(gaps, 1):
        hours = gap["gap_seconds"] / 3600
        logging.info(
            f"  Gap {i:>3}: {gap['gap_start']}  ->  {gap['gap_end']}"
            f"  |  {gap['missing_steps']} missing step(s)  ({hours:.1f} h)"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Check JSON timeseries files for gaps."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "docs" / "data",
        help="Directory containing JSON data files (default: docs/data/)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Check a single JSON file instead of the whole directory.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file path (default: log to console)",
    )
    args = parser.parse_args()

    log_config = {
        "level": getattr(logging, args.log_level.upper(), logging.INFO),
        "format": "%(asctime)s %(levelname)s %(message)s",
        "force": True,
    }
    if args.log_file:
        log_config["filename"] = args.log_file
    logging.basicConfig(**log_config)

    if args.file:
        files = [args.file]
    else:
        files = sorted(args.data_dir.glob("*.json"))
        if not files:
            logging.warning(f"No JSON files found in {args.data_dir}")
            return

    for filepath in files:
        check_file(filepath)

    logging.info("=" * 60)
    logging.info("Done.")


if __name__ == "__main__":
    main()
