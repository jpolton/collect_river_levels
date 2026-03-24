import urllib.request, urllib.parse, json, os, logging

# Configure basic logging
logging.basicConfig(level=logging.INFO)

try:
    NRW_KEY = os.environ.get("NRW_KEY")
    if not NRW_KEY:
        # Fallback to config_keys if exists, for backward compatibility or local testing
        try:
            import config_keys
            NRW_KEY = config_keys.NRW_KEY
        except (ImportError, AttributeError):
            # Try to find config_keys in parent directory if it's not in path
            try:
                import sys
                from pathlib import Path
                parent_dir = str(Path(__file__).resolve().parent.parent)
                if parent_dir not in sys.path:
                    sys.path.append(parent_dir)
                import config_keys
                NRW_KEY = config_keys.NRW_KEY
            except (ImportError, AttributeError):
                logging.error('Need a NRW API Key (set NRW_KEY environment variable or config_keys.py).')
                NRW_KEY = None
except Exception as e:
    logging.error(f'Error loading NRW API Key: {e}')
    NRW_KEY = None


from datetime import datetime, timedelta

def fetch_historical_data(station_id, ndays=3, parameter=41):
    # Calculate date range
    to_date_dt = datetime.now() + timedelta(days=1) # Ensure the to_date is from the upcoming midnight
    from_date_dt = to_date_dt - timedelta(days=ndays)
    
    # Format dates as strings (YYYY-MM-DD)
    to_date = to_date_dt.strftime('%Y-%m-%d')
    from_date = from_date_dt.strftime('%Y-%m-%d')

    base_url = "https://api.naturalresources.wales/rivers-and-seas/v1/api/StationData/historical"
    params = {
        "location": station_id,
        "parameter": parameter,
        "from": from_date,
        "to": to_date
    }
    query_string = urllib.parse.urlencode(params)
    url = f"{base_url}?{query_string}"
    
    hdr ={
    # Request headers
    'Cache-Control': 'no-cache',
    'Ocp-Apim-Subscription-Key': NRW_KEY,
    }

    req = urllib.request.Request(url, headers=hdr)
    req.get_method = lambda: 'GET'
    
    response = urllib.request.urlopen(req)
    # print(f"Status: {response.getcode()}")
    raw_data = json.loads(response.read())
    
    # Transform to match EA API structure (items list with dateTime and value)
    items = []
    if 'parameterReadings' in raw_data:
        for reading in raw_data['parameterReadings']:
            items.append({
                "dateTime": reading['time'],
                "value": reading['value']
            })
            
    return {"items": items}

if __name__ == "__main__":
    try:
        # Example usage
        ndays = 3
        station_id = 4173 # NRW: Ironbridge
        
        data = fetch_historical_data(station_id, ndays, parameter=41)
        
        if 'items' in data and len(data['items']) > 0:
            readings = data['items']
            print(f"Count: {len(readings)}")
            print(f"First: {readings[0]}")
            print(f"Last:  {readings[-1]}")
        else:
            print("No readings found in items")

    except Exception as e:
        print(e)
