#!/usr/bin/env python3
"""
db_to_json.py — Export SQLite timeseries data to JSON files (one per station).

Reads from timeseries.sqlite and creates/updates JSON files in docs/data/
matching the existing format:
{
  "station_key": "chester",
  "station_name": "Chester",
  "source": "EA",
  "generated_at": "2026-02-10T22:05:48.272602+00:00",
  "data": [
    {"ts_utc": 1770077700, "value": 5.114},
    ...
  ]
}

Usage:
  python db_to_json.py --db ../docs/data/timeseries.sqlite --output-dir ../docs/data
  python db_to_json.py  # uses defaults

Author: you
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

# Add current directory to sys.path to ensure we can import local modules
sys.path.append(os.getcwd())

# Import STATIONS from flask_app to get station metadata (name, etc.)
try:
    from flask_app import STATIONS
except Exception as e:
    raise SystemExit(
        f"Could not import STATIONS from flask_app.py: {e}\n"
        "Make sure db_to_json.py is in the same directory as flask_app.py"
    )

DEFAULT_DB_PATH = os.environ.get("TS_DB_PATH", "../docs/data/timeseries.sqlite")
DEFAULT_OUTPUT_DIR = "../docs/data"


def ts_utc_to_str(ts: int) -> str:
    """Convert a UTC Unix timestamp to a formatted datetime string (YYYY-MM-DD HH:MM:SS)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def export_station_to_json(conn: sqlite3.Connection, station_key: str, output_dir: str):
    """
    Export a single station's data to a JSON file.
    
    Args:
        conn: SQLite connection
        station_key: Station identifier (e.g., "chester")
        output_dir: Directory to write JSON files
    """
    # Get station metadata from STATIONS dict
    if station_key not in STATIONS:
        print(f"Warning: Station '{station_key}' not found in STATIONS config, skipping")
        return
    
    station_meta = STATIONS[station_key]
    
    # Query all readings for this station, ordered by timestamp
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts_utc, value
        FROM readings
        WHERE station_key = ?
        ORDER BY ts_utc ASC;
        """,
        (station_key,)
    )
    
    rows = cur.fetchall()
    
    if not rows:
        print(f"No data found for station '{station_key}', skipping")
        return
    
    # Build the data array
    data = [{"datetime": ts_utc_to_str(ts), "ts_utc": ts, "value": val} for ts, val in rows]
    
    # Create the output JSON structure
    output = {
        "station_key": station_key,
        "station_name": station_meta.get("name", station_key.title()),
        "source": station_meta.get("source", "Unknown"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": data
    }
    
    # Write to file
    output_path = os.path.join(output_dir, f"{station_key}.json")
    with open(output_path, "w") as f:
        json.dump(output, f)
    
    print(f"[OK] Exported {len(data)} readings for '{station_key}' to {output_path}")


def export_all_stations(db_path: str, output_dir: str):
    """
    Export all stations from the database to individual JSON files.
    
    Args:
        db_path: Path to SQLite database
        output_dir: Directory to write JSON files
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Connect to database
    conn = sqlite3.connect(db_path, timeout=30)
    
    # Get list of all stations in the database
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT station_key FROM readings ORDER BY station_key;")
    station_keys = [row[0] for row in cur.fetchall()]
    
    if not station_keys:
        print("No stations found in database")
        return
    
    print(f"Found {len(station_keys)} station(s) in database: {', '.join(station_keys)}")
    print(f"Exporting to: {os.path.abspath(output_dir)}\n")
    
    # Export each station
    for station_key in station_keys:
        export_station_to_json(conn, station_key, output_dir)
    
    conn.close()
    print(f"\n[OK] Export complete! {len(station_keys)} file(s) written.")


def main():
    parser = argparse.ArgumentParser(
        description="Export SQLite timeseries data to JSON files (one per station)."
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write JSON files (default: {DEFAULT_OUTPUT_DIR})"
    )
    args = parser.parse_args()
    
    # Check if database exists
    if not os.path.exists(args.db):
        print(f"Error: Database file not found: {args.db}")
        sys.exit(1)
    
    export_all_stations(args.db, args.output_dir)


if __name__ == "__main__":
    main()
