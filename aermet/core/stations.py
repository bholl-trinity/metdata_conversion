"""
Station discovery — find nearby surface (ISD) and upper air (IGRA) stations.

Downloads and caches station inventories from NCEI, searches by distance
from a project location, and ranks candidates.
"""

import csv
import os
import requests

from .geocode import haversine_km
from .igra import parse_igra_station_list

_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
IGRA_STATION_LIST_URL = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/doc/igra2-station-list.txt"


# ---------------------------------------------------------------------------
# ISD surface stations
# ---------------------------------------------------------------------------

def ensure_isd_station_list():
    """Download ISD station history CSV if not cached locally."""
    path = os.path.join(_DATA_DIR, 'isd-history.csv')
    if os.path.exists(path):
        return path
    os.makedirs(_DATA_DIR, exist_ok=True)
    resp = requests.get(ISD_HISTORY_URL, timeout=60)
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
    Find ISD surface stations near a location that have data coverage
    for the requested period. Returns list sorted by distance.
    """
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
    resp = requests.get(IGRA_STATION_LIST_URL, timeout=60)
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
