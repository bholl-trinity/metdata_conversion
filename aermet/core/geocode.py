"""
Geocoding module — resolves user-provided locations to lat/lon.

Supports:
  - Street address (via Nominatim OpenStreetMap API)
  - Direct lat/lon entry
  - ICAO airport code (bundled database)
"""

import csv
import json
import math
import os

from .http import get as http_get

# Bundled airport database path (relative to this file)
_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


def geocode_address(address):
    """
    Geocode a street address using Nominatim (OpenStreetMap).
    Returns dict with lat, lon, display_name or raises ValueError.
    """
    url = 'https://nominatim.openstreetmap.org/search'
    params = {
        'q': address,
        'format': 'json',
        'limit': 1,
        'addressdetails': 1,
    }
    headers = {'User-Agent': 'AERMET-Automation-Tool/1.0'}
    resp = http_get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f'No results found for address: {address}')

    r = results[0]
    country_code = r.get('address', {}).get('country_code', '')
    return {
        'lat': float(r['lat']),
        'lon': float(r['lon']),
        'display_name': r.get('display_name', ''),
        'country_code': country_code.upper(),
        'is_us': country_code.lower() == 'us',
    }


def geocode_airport(icao_code):
    """
    Look up an ICAO airport code from the bundled database.
    Returns dict with lat, lon, name, country_code, is_us.
    """
    icao_code = icao_code.strip().upper()
    db_path = os.path.join(_DATA_DIR, 'airports.csv')

    if not os.path.exists(db_path):
        # Fall back to Nominatim
        return geocode_address(f'{icao_code} airport')

    with open(db_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('icao', '').strip().upper() == icao_code:
                cc = row.get('country', '').strip().upper()
                return {
                    'lat': float(row['lat']),
                    'lon': float(row['lon']),
                    'name': row.get('name', icao_code),
                    'country_code': cc,
                    'is_us': cc == 'US',
                }

    raise ValueError(f'Airport code {icao_code} not found in database')


def geocode_latlon(lat, lon):
    """
    Validate and return a direct lat/lon entry.
    Determines country via simple bounding box (US check).
    """
    lat = float(lat)
    lon = float(lon)
    if lat < -90 or lat > 90:
        raise ValueError(f'Invalid latitude: {lat}')
    if lon < -180 or lon > 180:
        raise ValueError(f'Invalid longitude: {lon}')

    is_us = _is_conus(lat, lon)
    return {
        'lat': lat,
        'lon': lon,
        'display_name': f'{lat:.4f}, {lon:.4f}',
        'country_code': 'US' if is_us else '',
        'is_us': is_us,
    }


def _is_conus(lat, lon):
    """Simple bounding-box check for continental US."""
    return 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0


def reverse_geocode(lat, lon):
    """Reverse geocode to determine country."""
    url = 'https://nominatim.openstreetmap.org/reverse'
    params = {'lat': lat, 'lon': lon, 'format': 'json', 'zoom': 3}
    headers = {'User-Agent': 'AERMET-Automation-Tool/1.0'}
    try:
        resp = http_get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        cc = data.get('address', {}).get('country_code', '').upper()
        return {'country_code': cc, 'is_us': cc == 'US'}
    except Exception:
        return {'country_code': '', 'is_us': _is_conus(lat, lon)}


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points."""
    R = 6371.0
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
