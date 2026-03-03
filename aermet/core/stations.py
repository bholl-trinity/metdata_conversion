"""
Station discovery — find nearby surface (GHCNh / ISD) and upper air (IGRA)
stations.

Downloads and caches station inventories from NCEI, searches by distance
from a project location, and ranks candidates.

Primary surface station source: GHCNh station list (next-gen replacement
for ISD).  Falls back to ISD history if GHCNh is unavailable.
"""

import csv
import os

from .http import get as http_get

from .geocode import haversine_km
from .igra import parse_igra_station_list

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# GHCNh (preferred — the actual data source we download from)
GHCNH_STATION_LIST_URL = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt"
GHCNH_INVENTORY_URL = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-inventory.txt"

# ISD (legacy fallback)
ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

IGRA_STATION_LIST_URL = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/doc/igra2-station-list.txt"


# ---------------------------------------------------------------------------
# GHCNh surface stations (preferred)
# ---------------------------------------------------------------------------

def ensure_ghcnh_station_list():
    """Download GHCNh station list if not cached locally."""
    path = os.path.join(_DATA_DIR, 'ghcnh-station-list.txt')
    if os.path.exists(path):
        return path
    os.makedirs(_DATA_DIR, exist_ok=True)
    resp = http_get(GHCNH_STATION_LIST_URL, timeout=60)
    resp.raise_for_status()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return path


def ensure_ghcnh_inventory():
    """Download GHCNh inventory (obs counts per month) if not cached."""
    path = os.path.join(_DATA_DIR, 'ghcnh-inventory.txt')
    if os.path.exists(path):
        return path
    os.makedirs(_DATA_DIR, exist_ok=True)
    resp = http_get(GHCNH_INVENTORY_URL, timeout=120)
    resp.raise_for_status()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return path


def load_ghcnh_stations(path=None):
    """
    Parse the GHCNh station list (fixed-width format).

    Format (from NCEI docs):
      Col  1-11: ID (11-char GHCNh station ID)
      Col 13-20: LATITUDE
      Col 22-30: LONGITUDE
      Col 32-37: ELEVATION (m)
      Col 39-40: STATE (US only)
      Col 42-71: NAME
      Col 73-75: GSN FLAG
      Col 77-79: HCN/CRN FLAG
      Col 81-85: WMO ID
      Col 87-90: ICAO
    """
    if path is None:
        path = ensure_ghcnh_station_list()

    stations = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if len(line.strip()) < 40:
                continue
            try:
                sid = line[0:11].strip()
                lat = float(line[12:20].strip())
                lon = float(line[21:30].strip())
                elev_str = line[31:37].strip()
                elev = float(elev_str) if elev_str and elev_str != '-999.9' else None
                state = line[38:40].strip() if len(line) > 40 else ''
                name = line[41:71].strip() if len(line) > 71 else ''
                wmo_id = line[80:85].strip() if len(line) > 85 else ''
                icao = line[86:90].strip() if len(line) > 90 else ''

                # Country code is the first 2 chars of the station ID
                country = sid[:2] if len(sid) >= 2 else ''

                stations.append({
                    'ghcnh_id': sid,
                    'lat': lat,
                    'lon': lon,
                    'elev': elev,
                    'state': state,
                    'name': name,
                    'country': country,
                    'wmo_id': wmo_id,
                    'icao': icao,
                })
            except (ValueError, IndexError):
                continue
    return stations


def load_ghcnh_inventory(path=None):
    """
    Parse the GHCNh inventory file to get observation counts per station/month.

    Returns dict: { station_id: { (year, month): count, ... }, ... }

    The inventory is a fixed-width file with format similar to GHCNd:
      Col 1-11:  ID
      Col 13-16: YEAR
      Col 18-19: MONTH
      Col 21+:   COUNT (number of records)
    """
    if path is None:
        path = ensure_ghcnh_inventory()

    inventory = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if len(line.strip()) < 20:
                continue
            try:
                sid = line[0:11].strip()
                year = int(line[12:16].strip())
                month = int(line[17:19].strip())
                count = int(line[20:].strip())
                if sid not in inventory:
                    inventory[sid] = {}
                inventory[sid][(year, month)] = count
            except (ValueError, IndexError):
                continue
    return inventory


def get_ghcnh_station_year_range(inventory, station_id):
    """Get first and last year of data for a GHCNh station from inventory."""
    months = inventory.get(station_id, {})
    if not months:
        return None, None
    years = [ym[0] for ym in months.keys()]
    return min(years), max(years)


def check_ghcnh_completeness(inventory, station_id, start_year, end_year,
                              min_obs_per_month=200):
    """
    Quick data completeness screen for a GHCNh station.

    Returns dict with:
      - complete_months: count of months meeting min_obs_per_month
      - total_months: total months in requested range
      - pct_complete: percentage
    """
    months = inventory.get(station_id, {})
    total = 0
    complete = 0
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            total += 1
            count = months.get((year, month), 0)
            if count >= min_obs_per_month:
                complete += 1
    pct = round(complete / total * 100, 1) if total > 0 else 0
    return {
        'complete_months': complete,
        'total_months': total,
        'pct_complete': pct,
    }


def find_nearby_ghcnh_stations(lat, lon, start_year=None, end_year=None,
                                max_distance_km=150, max_results=20):
    """
    Find GHCNh surface stations near a location.

    If start/end year provided and inventory is available, includes
    a basic completeness check.  Returns list sorted by distance.
    """
    all_stations = load_ghcnh_stations()

    # Try to load inventory for completeness screening
    inv = None
    if start_year and end_year:
        try:
            inv = load_ghcnh_inventory()
        except Exception:
            pass  # inventory is optional

    candidates = []
    for s in all_stations:
        dist = haversine_km(lat, lon, s['lat'], s['lon'])
        if dist > max_distance_km:
            continue

        s_copy = dict(s)
        s_copy['distance_km'] = round(dist, 1)

        if inv and start_year and end_year:
            first, last = get_ghcnh_station_year_range(inv, s['ghcnh_id'])
            if first is not None:
                s_copy['first_year'] = first
                s_copy['last_year'] = last
                # Skip stations with no data overlap
                if last < start_year or first > end_year:
                    continue
                comp = check_ghcnh_completeness(
                    inv, s['ghcnh_id'], start_year, end_year)
                s_copy['completeness'] = comp
            else:
                # No inventory data — include but flag
                s_copy['first_year'] = None
                s_copy['last_year'] = None

        candidates.append(s_copy)

    candidates.sort(key=lambda x: x['distance_km'])
    return candidates[:max_results]


# ---------------------------------------------------------------------------
# ISD surface stations (legacy fallback)
# ---------------------------------------------------------------------------

def ensure_isd_station_list():
    """Download ISD station history CSV if not cached locally."""
    path = os.path.join(_DATA_DIR, 'isd-history.csv')
    if os.path.exists(path):
        return path
    os.makedirs(_DATA_DIR, exist_ok=True)
    resp = http_get(ISD_HISTORY_URL, timeout=60)
    resp.raise_for_status()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return path


def load_isd_stations(path=None):
    """Parse ISD station history CSV into list of dicts."""
    if path is None:
        path = ensure_isd_station_list()

    stations = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = row.get('LAT', '').strip()
                lon = row.get('LON', '').strip()
                if not lat or not lon or lat == '' or lon == '':
                    continue
                lat = float(lat)
                lon = float(lon)
                if lat == 0 and lon == 0:
                    continue

                usaf = row.get('USAF', '999999').strip()
                wban = row.get('WBAN', '99999').strip()
                name = row.get('STATION NAME', '').strip()
                ctry = row.get('CTRY', '').strip()
                state = row.get('STATE', '').strip()
                icao = row.get('ICAO', '').strip()
                elev = row.get('ELEV(M)', '').strip()
                begin = row.get('BEGIN', '').strip()
                end = row.get('END', '').strip()

                # Parse begin/end dates (YYYYMMDD format)
                first_year = int(begin[:4]) if begin and len(begin) >= 4 else 9999
                last_year = int(end[:4]) if end and len(end) >= 4 else 0

                stations.append({
                    'usaf': usaf,
                    'wban': wban,
                    'name': name,
                    'country': ctry,
                    'state': state,
                    'icao': icao,
                    'lat': lat,
                    'lon': lon,
                    'elev': float(elev) if elev else None,
                    'first_year': first_year,
                    'last_year': last_year,
                    'begin': begin,
                    'end': end,
                })
            except (ValueError, KeyError):
                continue
    return stations


def find_nearby_surface_stations(lat, lon, start_year, end_year,
                                  max_distance_km=150, max_results=20):
    """
    Find surface stations near a location that have data coverage
    for the requested period.  Tries GHCNh first (preferred), falls
    back to ISD if GHCNh station list isn't available.
    Returns list sorted by distance.
    """
    try:
        return find_nearby_ghcnh_stations(
            lat, lon, start_year, end_year,
            max_distance_km=max_distance_km, max_results=max_results)
    except Exception:
        pass

    # Fallback to ISD
    all_stations = load_isd_stations()
    candidates = []

    for s in all_stations:
        dist = haversine_km(lat, lon, s['lat'], s['lon'])
        if dist > max_distance_km:
            continue
        # Check date range overlap
        if s['last_year'] < start_year or s['first_year'] > end_year:
            continue
        s_copy = dict(s)
        s_copy['distance_km'] = round(dist, 1)
        candidates.append(s_copy)

    candidates.sort(key=lambda x: x['distance_km'])
    return candidates[:max_results]


# ---------------------------------------------------------------------------
# IGRA upper air stations
# ---------------------------------------------------------------------------

def ensure_igra_station_list():
    """Download IGRA station list if not cached locally."""
    path = os.path.join(_DATA_DIR, 'igra2-station-list.txt')
    if os.path.exists(path):
        return path
    os.makedirs(_DATA_DIR, exist_ok=True)
    resp = http_get(IGRA_STATION_LIST_URL, timeout=60)
    resp.raise_for_status()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return path


def load_igra_stations(path=None):
    """Load IGRA station inventory."""
    if path is None:
        path = ensure_igra_station_list()
    return parse_igra_station_list(path)


def find_nearby_upper_air_stations(lat, lon, start_year, end_year,
                                    max_distance_km=400, max_results=10):
    """
    Find IGRA upper air stations near a location with data coverage.
    Uses a larger search radius than surface since UA stations are sparser.
    """
    all_stations = load_igra_stations()
    candidates = []

    for s in all_stations:
        dist = haversine_km(lat, lon, s['lat'], s['lon'])
        if dist > max_distance_km:
            continue
        if s['last_year'] < start_year or s['first_year'] > end_year:
            continue
        s_copy = dict(s)
        s_copy['distance_km'] = round(dist, 1)
        candidates.append(s_copy)

    candidates.sort(key=lambda x: x['distance_km'])
    return candidates[:max_results]
