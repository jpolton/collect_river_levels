"""
Flask web app for river water level monitoring.

conda activate weir_waterlevel_web_env
python flask_app.py

Access at http://localhost:5000 in your browser.
"""

from flask import Flask, render_template, jsonify, request
import requests
import pandas as pd
from datetime import datetime
import numpy as np
import json
import sys
import os

# NRW API import


try:
    # Add parent directory to path to find nrw_api if running as script
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nrw_api.nrw_api import fetch_nrw_station_data
except Exception as e:
    print(f"Warning: NRW API not available ({e}). NRW stations will not work.")

app = Flask(__name__, template_folder='docs')

# Station definitions.
STATIONS = {
    "chester": {
        "id": "067033_TG_148",
        "name": "Chester",
        "source": "EA",
        "description": "Environment Agency monitoring station"
        # The weir has an id: https://environment.data.gov.uk/flood-monitoring/id/stations/067033 but it doesn't seem to have any data
    },
    "liverpool": {
        "id": "E70124",
        "name": "Liverpool",
        "source": "EA",
        "description": "Environment Agency monitoring station"
    },
    "ironbridge": {
        "id": "4173", #NRW:4273 Shoothill:968,
        "name": "Ironbridge",
        "source": "NRW",
        "description": "Natural Resources Wales monitoring station",
        "parameter_id": 41
        # Addtional, EA, data on IronBridge (doesn't seem to work): https://environment.data.gov.uk/flood-monitoring/id/stations/067027_TG_127/stageScale
    },
    "farndon": {
        "id": "4170", #NRW:4170 Shoothill:972,
        "name": "Farndon",
        "source": "NRW",
        "description": "Natural Resources Wales monitoring station",
        "parameter_id": 40
    },
    "queens_park": {
        "id": "SJ46_109", #EA:SJ46_109 Shoothill:10831,
        "name": "Queens Park ground water level",
        "source": "EA",
        "description": "Environment Agency monitoring station"
    }
}
# Extra EA data on Finchett's Gutter etc: https://environment.data.gov.uk/flood-monitoring/id/stations?lat=53.1899&long=-2.8853&dist=10


def fetch_ea_station_data(station_id: str, ndays: int = 7) -> dict:
    """Fetch readings from Environment Agency flood monitoring API, for the last `ndays` days"""
    url = f"https://environment.data.gov.uk/flood-monitoring/id/stations/{station_id}/readings"
    #if ndays == 1:
    #    params = {"today": ""}
    #else:
    date_end = np.datetime64('now') - np.timedelta64(int(1), 'D')
    # subtract ndays days from date_end
    date_start = date_end - np.timedelta64(int(ndays), 'D')

    py_dt_start = date_start.astype('datetime64[ms]').item()   # convert to Python datetime
    py_dt_end = date_end.astype('datetime64[ms]').item()
    print(py_dt_start.strftime('%Y-%m-%dT%H:%M:%SZ'))
    print(py_dt_end.strftime('%Y-%m-%dT%H:%M:%SZ'))
    # Use full ISO timestamp for enddate to capture all available data
    params = {"startdate": py_dt_start.strftime('%Y-%m-%d'), "enddate": py_dt_end.strftime('%Y-%m-%d')}
    #params = {"since": py_dt_start.strftime('%Y-%m-%dT00:00:00Z'), "_limit": 800}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching EA data: {e}")
        return {"items": []}





def get_station_data(station_key: str, ndays: int = 1) -> dict:
    """Fetch and format data for a specific station."""
    if station_key not in STATIONS:
        return {"error": "Station not found"}
    
    station = STATIONS[station_key]
    
    try:
        if station["source"] == "EA":
            data = fetch_ea_station_data(station["id"], ndays=ndays)
            readings = [
                {
                    "dateTime": item["dateTime"],
                    "value": item["value"]
                }
                for item in data.get("items", [])
            ]
        elif station["source"] == "NRW":
            parameter_id = station.get("parameter_id", 41) # Default to 41 if not specified
            data = fetch_nrw_station_data(station["id"], ndays=ndays, parameter=parameter_id)
            readings = [
                {
                    "dateTime": item["dateTime"],
                    "value": item["value"]
                }
                for item in data.get("items", [])
            ]
        
        if not readings:
            return {
                "station": station,
                "readings": [],
                "error": "No data available"
            }
        
        df = pd.DataFrame(readings)
        # Parse datetimes robustly (handle fractional seconds and timezones)
        original_times = df["dateTime"].astype(str).copy()
        df["dateTime"] = pd.to_datetime(df["dateTime"], utc=True, errors='coerce')
        # For any entries that remain NaT, try parsing with dateutil
        if df["dateTime"].isna().any():
            try:
                from dateutil import parser as dateutil_parser
                mask = df["dateTime"].isna()
                for idx in df[mask].index:
                    s = original_times.loc[idx]
                    try:
                        parsed = dateutil_parser.parse(s)
                        # ensure timezone-aware -> convert to UTC
                        if parsed.tzinfo is not None:
                            parsed = parsed.astimezone(tz=None)
                        df.at[idx, "dateTime"] = pd.to_datetime(parsed)
                    except Exception:
                        df.at[idx, "dateTime"] = pd.NaT
            except Exception:
                # If dateutil not available, leave NaT entries as is
                pass
        df = df.sort_values("dateTime")
        
        return {
            "station": station,
            "readings": [
                {
                    "dateTime": row["dateTime"].isoformat(),
                    "value": float(row["value"])
                }
                for _, row in df.iterrows()
            ],
            "stats": {
                "min": float(df["value"].min()),
                "max": float(df["value"].max()),
                "mean": float(df["value"].mean()),
                "count": len(df)
            }
        }
    except Exception as e:
        return {
            "station": station,
            "readings": [],
            "error": str(e)
        }


@app.route("/")
def index():
    """Serve main page."""
    return render_template("index.html", stations=STATIONS)


@app.route("/api/station/<station_key>")
def api_station(station_key):
    """API endpoint for station data."""
    # allow client to request last N days via ?ndays=
    try:
        ndays = int(request.args.get('ndays', 1))
        if ndays < 1:
            ndays = 1
    except Exception:
        ndays = 1
    data = get_station_data(station_key, ndays=ndays)
    return jsonify(data)


@app.route("/api/all")
def api_all():
    """API endpoint for all stations data."""
    all_data = {}
    # allow a common ndays parameter for all stations
    try:
        ndays = int(request.args.get('ndays', 1))
        if ndays < 1:
            ndays = 1
    except Exception:
        ndays = 1
    for station_key in STATIONS.keys():
        all_data[station_key] = get_station_data(station_key, ndays=ndays)
    return jsonify(all_data)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5002)
