"""
Data download module — acquires surface (GHCNh), upper air (IGRA),
and 1-minute ASOS data from NCEI.
"""

import os
import requests

from .ghcnh_to_isd import convert_ghcnh_file
from .igra import download_igra_data, trim_igra_to_years

# NCEI GHCNh download base URL
GHCNH_BASE_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-hourly/access"

# 1-minute ASOS data base URL
ONEMIN_BASE_URL = "https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access"


def download_ghcnh(station_id, output_dir, progress_cb=None):
    """
    Download GHCNh data for a station from NCEI.

    GHCNh files are named like: GHCNh_USW00014771_por.psv
    (period-of-record, single file per station)

    Returns path to downloaded .psv file.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Try period-of-record file first
    filename = f"GHCNh_{station_id}_por.psv"
    url = f"{GHCNH_BASE_URL}/{filename}"

    if progress_cb:
        progress_cb('downloading', f'Downloading GHCNh surface data for {station_id}...')

    output_path = os.path.join(output_dir, filename)

    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()

    total = int(resp.headers.get('content-length', 0))
    downloaded = 0
    with open(output_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if progress_cb and total > 0:
                pct = round(downloaded / total * 100)
                progress_cb('downloading', f'Downloading surface data... {pct}%')

    if progress_cb:
        progress_cb('done', f'Downloaded {filename}')

    return output_path


def convert_surface_data(ghcnh_path, isd_output_path, progress_cb=None):
    """
    Convert downloaded GHCNh PSV to ISD format for AERMET.
    Returns conversion stats dict.
    """
    if progress_cb:
        progress_cb('converting', 'Converting GHCNh to ISD format...')

    def _progress(i, total):
        if progress_cb:
            pct = round(i / total * 100) if total else 0
            progress_cb('converting', f'Converting records... {pct}%')

    result = convert_ghcnh_file(ghcnh_path, isd_output_path, _progress)

    if progress_cb:
        progress_cb('done', f'Converted {result["converted"]} records to ISD format')

    return result


def download_and_convert_surface(station_id, output_dir, progress_cb=None):
    """
    Download GHCNh and convert to ISD in one step.
    Returns dict with paths and stats.
    """
    ghcnh_path = download_ghcnh(station_id, output_dir, progress_cb)
    isd_path = os.path.join(output_dir, f'{station_id}.ish')
    stats = convert_surface_data(ghcnh_path, isd_path, progress_cb)
    return {
        'ghcnh_path': ghcnh_path,
        'isd_path': isd_path,
        'stats': stats,
    }


def download_and_trim_upper_air(igra_station_id, output_dir,
                                 start_year, end_year, progress_cb=None):
    """
    Download full IGRA file and trim to years of interest.
    Returns dict with paths and stats.
    """
    os.makedirs(output_dir, exist_ok=True)
    full_path = os.path.join(output_dir, f'{igra_station_id}_full.dat')
    trimmed_path = os.path.join(output_dir, f'{igra_station_id}_{start_year}_{end_year}.dat')

    download_igra_data(igra_station_id, full_path, progress_cb)

    if progress_cb:
        progress_cb('trimming', f'Trimming IGRA data to {start_year}-{end_year}...')

    stats = trim_igra_to_years(full_path, trimmed_path, start_year, end_year)

    if progress_cb:
        progress_cb('done', f'Trimmed IGRA: kept {stats["kept_soundings"]} of {stats["total_soundings"]} soundings')

    # Remove the full file to save space
    try:
        os.remove(full_path)
    except OSError:
        pass

    return {
        'igra_path': trimmed_path,
        'stats': stats,
    }


def download_one_minute_asos(station_wban, year, output_dir, progress_cb=None):
    """
    Download 1-minute ASOS data for a station and year.

    Files are in subdirectories by year: {YEAR}/{WBAN}.dat
    Returns path to downloaded file or None if not available.
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1-min ASOS data is organized by year
    wban = str(station_wban).zfill(5)
    filename = f"{wban}.dat"
    url = f"{ONEMIN_BASE_URL}/{year}/{filename}"

    output_path = os.path.join(output_dir, f'onemin_{wban}_{year}.dat')

    if progress_cb:
        progress_cb('downloading', f'Downloading 1-min ASOS for WBAN {wban}, year {year}...')

    try:
        resp = requests.get(url, timeout=120)
        if resp.status_code == 404:
            if progress_cb:
                progress_cb('skipped', f'No 1-min data available for WBAN {wban}, {year}')
            return None
        resp.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(resp.content)
        if progress_cb:
            progress_cb('done', f'Downloaded 1-min ASOS for {year}')
        return output_path
    except requests.RequestException:
        if progress_cb:
            progress_cb('error', f'Failed to download 1-min data for {year}')
        return None
