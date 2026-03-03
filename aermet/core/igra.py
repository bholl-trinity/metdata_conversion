"""
IGRA (Integrated Global Radiosonde Archive) utilities.

IGRA data files are text-based with header lines starting with '#'.
Header format:
  #USM00072451 1973 01 01 00  ...
  ^            ^    ^  ^  ^
  station_id   year mo dy hr

Data lines follow until the next header line.
This module downloads full-history IGRA files and trims them to years of interest.
"""

import os
import re
import requests

# NCEI IGRA data archive base URL
IGRA_DATA_URL = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/data-por"
IGRA_STATION_LIST_URL = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/doc/igra2-station-list.txt"


def download_igra_station_list(output_path):
    """Download the IGRA station inventory file."""
    resp = requests.get(IGRA_STATION_LIST_URL, timeout=60)
    resp.raise_for_status()
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    return output_path


def parse_igra_station_list(path):
    """
    Parse the IGRA station list into a list of dicts.

    The IGRA station list is a fixed-width format:
    Col  1-  2: country code
    Col  3- 13: station ID (e.g., USM00072451)
    Col 14- 20: latitude (decimal degrees, + = N)
    Col 21- 30: longitude (decimal degrees, + = E)
    Col 31- 37: elevation (meters)
    Col 39- 40: state (US only)
    Col 42- 71: station name
    Col 73- 76: first year of data
    Col 78- 81: last year of data
    Col 83- 88: number of soundings
    """
    stations = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if len(line.strip()) < 80:
                continue
            try:
                sid = line[0:11].strip()
                lat = float(line[12:20].strip())
                lon = float(line[21:30].strip())
                elev = float(line[31:37].strip())
                state = line[38:40].strip()
                name = line[41:71].strip()
                first_year = int(line[72:76].strip())
                last_year = int(line[77:81].strip())
                stations.append({
                    'id': sid,
                    'lat': lat,
                    'lon': lon,
                    'elev': elev,
                    'state': state,
                    'name': name,
                    'first_year': first_year,
                    'last_year': last_year,
                })
            except (ValueError, IndexError):
                continue
    return stations


def download_igra_data(station_id, output_path, progress_cb=None):
    """
    Download the full period-of-record IGRA data file for a station.

    IGRA files are typically named like: USM00072451-data.txt.zip
    We download the uncompressed version from the data-por directory.
    """
    # IGRA data files are named {station_id}-data.txt.zip (zipped)
    # or we can try the derived product
    url = f"{IGRA_DATA_URL}/{station_id}-data.txt.zip"

    if progress_cb:
        progress_cb('downloading', f'Downloading IGRA data for {station_id}...')

    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()

    # It's a zip file, save and extract
    import zipfile
    import io

    zip_data = io.BytesIO(resp.content)
    with zipfile.ZipFile(zip_data) as zf:
        # The zip should contain one file: {station_id}-data.txt
        names = zf.namelist()
        if not names:
            raise ValueError(f"Empty zip file for station {station_id}")
        with zf.open(names[0]) as zentry:
            with open(output_path, 'wb') as f:
                f.write(zentry.read())

    if progress_cb:
        progress_cb('done', f'Downloaded IGRA data for {station_id}')

    return output_path


def parse_igra_header(line):
    """
    Parse an IGRA header line.

    Header format: #USM00072451 1973 01 01 00 ...
    Returns dict with station_id, year, month, day, hour or None if not a header.
    """
    if not line.startswith('#'):
        return None
    parts = line[1:].split()
    if len(parts) < 5:
        return None
    try:
        return {
            'station_id': parts[0],
            'year': int(parts[1]),
            'month': int(parts[2]),
            'day': int(parts[3]),
            'hour': int(parts[4]),
        }
    except (ValueError, IndexError):
        return None


def trim_igra_to_years(input_path, output_path, start_year, end_year):
    """
    Extract only the soundings within [start_year, end_year] from an IGRA file.

    Reads the full-history IGRA file line by line, writes only the headers
    and data lines that fall within the requested year range.

    Returns dict with stats: total_soundings, kept_soundings.
    """
    total = 0
    kept = 0
    keeping = False

    with open(input_path, 'r', encoding='utf-8', errors='replace') as fin, \
         open(output_path, 'w', encoding='utf-8') as fout:
        for line in fin:
            if line.startswith('#'):
                total += 1
                header = parse_igra_header(line)
                if header and start_year <= header['year'] <= end_year:
                    keeping = True
                    kept += 1
                    fout.write(line)
                else:
                    keeping = False
            else:
                if keeping:
                    fout.write(line)

    return {'total_soundings': total, 'kept_soundings': kept}


def get_igra_year_range(file_path):
    """Scan an IGRA file to determine the min and max years present."""
    min_year = 9999
    max_year = 0
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('#'):
                header = parse_igra_header(line)
                if header:
                    min_year = min(min_year, header['year'])
                    max_year = max(max_year, header['year'])
    return min_year, max_year
