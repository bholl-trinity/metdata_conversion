#!/usr/bin/env python3
"""
igra_fsl_tool.py

Download IGRA v2 upper air data from NCEI, convert to FSL format, and
produce per-year and combined output files suitable for CPRAMMET.

This tool automates the full pipeline:
  1. Download the full-history IGRA data archive for a station
  2. Trim to the requested year range
  3. Convert from IGRA v2 format to FSL format
  4. Write per-year files AND a combined multi-year file

Output file naming convention:
  Per-year:   <ID><YY>.rao        e.g., IAD22.rao
  Combined:   <ID><YY1><YY2>.rao  e.g., IAD2125.rao (2021-2025)

Usage:
  python igra_fsl_tool.py --station USM00072451 --name IAD \\
      --start-year 2021 --end-year 2025

  # With station metadata overrides:
  python igra_fsl_tool.py --station USM00072451 --name IAD \\
      --start-year 2021 --end-year 2025 \\
      --wban 93734 --lat 38.98 --lon -77.48 --elev 93.0

  # Specify output directory:
  python igra_fsl_tool.py --station USM00072451 --name IAD \\
      --start-year 2022 --end-year 2022 --outdir ./output

Requires: requests (pip install requests)
"""

import argparse
import io
import os
import sys
import zipfile
from datetime import datetime

try:
    import requests
    from requests.exceptions import SSLError
except ImportError:
    print("The 'requests' library is required. Install with: pip install requests")
    sys.exit(1)

# Import FSL conversion functions from igra_to_fsl.py
from igra_to_fsl import (
    parse_igra_header,
    parse_igra_data_line,
    read_igra_soundings,
    write_fsl_sounding,
    extract_wmo_number,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

IGRA_DATA_URL = (
    "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive"
    "/access/data-por"
)
IGRA_STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive"
    "/doc/igra2-station-list.txt"
)

# Try to use certifi for SSL if available
try:
    import certifi
    SSL_VERIFY = certifi.where()
except ImportError:
    SSL_VERIFY = True


def _ssl_get(url, **kwargs):
    """
    Wrapper around requests.get() that handles SSL certificate errors.

    First attempts the request with the configured CA bundle (certifi or
    system default).  If that fails with an SSL error, retries with
    verification disabled and warns the user.
    """
    kwargs.setdefault('verify', SSL_VERIFY)
    try:
        return requests.get(url, **kwargs)
    except SSLError:
        print("  WARNING: SSL certificate verification failed.")
        print("  Retrying without certificate verification.")
        print("  Tip: install or update the 'certifi' package to fix this permanently:")
        print("       pip install --upgrade certifi")
        kwargs['verify'] = False
        return requests.get(url, **kwargs)


# ============================================================================
# IGRA DOWNLOAD
# ============================================================================

def download_igra_data(station_id, output_path):
    """
    Download the full period-of-record IGRA data file for a station.

    Downloads the zipped file from NCEI and extracts the text data.
    """
    url = f"{IGRA_DATA_URL}/{station_id}-data.txt.zip"
    print(f"  Downloading {url}")

    resp = _ssl_get(url, timeout=300)
    resp.raise_for_status()

    zip_data = io.BytesIO(resp.content)
    with zipfile.ZipFile(zip_data) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError(f"Empty zip file for station {station_id}")
        with zf.open(names[0]) as zentry:
            with open(output_path, 'wb') as f:
                f.write(zentry.read())

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  Downloaded {size_mb:.1f} MB -> {output_path}")
    return output_path


def lookup_station_metadata(station_id):
    """
    Look up station metadata from the IGRA station list.

    Returns dict with lat, lon, elev, name, or empty dict if lookup fails.
    """
    print(f"  Looking up station metadata for {station_id}...")
    try:
        resp = _ssl_get(IGRA_STATION_LIST_URL, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Warning: Could not download station list: {e}")
        return {}

    for line in resp.text.splitlines():
        if len(line.strip()) < 80:
            continue
        sid = line[0:11].strip()
        if sid == station_id:
            try:
                return {
                    'lat': float(line[12:20].strip()),
                    'lon': float(line[21:30].strip()),
                    'elev': float(line[31:37].strip()),
                    'station_name': line[41:71].strip(),
                }
            except (ValueError, IndexError):
                break

    print(f"  Warning: Station {station_id} not found in IGRA station list")
    return {}


# ============================================================================
# TRIM
# ============================================================================

def trim_igra_to_years(input_path, output_path, start_year, end_year):
    """
    Extract only soundings within [start_year, end_year] from an IGRA file.

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


# ============================================================================
# FSL CONVERSION WITH YEAR-BASED OUTPUT
# ============================================================================

def convert_igra_to_fsl_by_year(input_path, outdir, station_name, station_meta,
                                start_year, end_year):
    """
    Convert an IGRA file to FSL, producing per-year and combined output files.

    Output files:
      <station_name><YY>.rao         per-year files
      <station_name><YY1><YY2>.rao   combined file (if multi-year)

    Returns dict with per-year sounding counts.
    """
    name = station_name.upper()

    # Build output filenames
    start_yy = f"{start_year % 100:02d}"
    end_yy = f"{end_year % 100:02d}"

    if start_year == end_year:
        combined_filename = f"{name}{start_yy}.rao"
    else:
        combined_filename = f"{name}{start_yy}{end_yy}.rao"

    combined_path = os.path.join(outdir, combined_filename)

    # Track per-year output files and counts
    year_files = {}    # year -> open file handle
    year_counts = {}   # year -> sounding count
    combined_count = 0

    try:
        combined_file = open(combined_path, 'w')

        for header, levels in read_igra_soundings(input_path):
            year = header['year']
            if year < start_year or year > end_year:
                continue

            # Write to combined file
            wrote = write_fsl_sounding(combined_file, header, levels, station_meta)
            if not wrote:
                continue
            combined_count += 1

            # Write to per-year file
            if year not in year_files:
                yy = f"{year % 100:02d}"
                year_filename = f"{name}{yy}.rao"
                year_path = os.path.join(outdir, year_filename)
                year_files[year] = open(year_path, 'w')
                year_counts[year] = 0

            write_fsl_sounding(year_files[year], header, levels, station_meta)
            year_counts[year] += 1

            if combined_count % 100 == 0:
                sys.stdout.write(f"\r  Converted {combined_count} soundings...")
                sys.stdout.flush()

    finally:
        combined_file.close()
        for f in year_files.values():
            f.close()

    return {
        'combined_path': combined_path,
        'combined_count': combined_count,
        'year_counts': year_counts,
    }


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Download IGRA upper air data and convert to FSL format"
    )
    parser.add_argument("--station", required=True,
                        help="IGRA station ID (e.g., USM00072451)")
    parser.add_argument("--name", required=True,
                        help="3-letter station ID for output filenames (e.g., IAD)")
    parser.add_argument("--start-year", type=int, required=True,
                        help="First year to process")
    parser.add_argument("--end-year", type=int, required=True,
                        help="Last year to process")
    parser.add_argument("--outdir", default=".",
                        help="Output directory (default: current directory)")
    parser.add_argument("--wban", default=None,
                        help="WBAN station number (default: 99999)")
    parser.add_argument("--lat", type=float, default=None,
                        help="Station latitude (overrides IGRA station list)")
    parser.add_argument("--lon", type=float, default=None,
                        help="Station longitude (overrides IGRA station list)")
    parser.add_argument("--elev", type=float, default=None,
                        help="Station elevation in meters (overrides IGRA station list)")
    parser.add_argument("--keep-igra", action="store_true",
                        help="Keep intermediate IGRA files (default: delete them)")
    parser.add_argument("--igra-file", default=None,
                        help="Use an existing IGRA file instead of downloading")

    args = parser.parse_args()

    if args.end_year < args.start_year:
        print("Error: --end-year must be >= --start-year")
        sys.exit(1)

    os.makedirs(args.outdir, exist_ok=True)

    print("=" * 70)
    print("IGRA to FSL Converter")
    print("=" * 70)
    print(f"  Station:    {args.station}")
    print(f"  Name:       {args.name}")
    print(f"  Years:      {args.start_year}-{args.end_year}")
    print(f"  Output dir: {os.path.abspath(args.outdir)}")
    print("=" * 70)
    print()

    # ---- Step 1: Get station metadata from IGRA station list ----
    print("Step 1: Station metadata")
    igra_meta = {}
    if not args.igra_file:
        igra_meta = lookup_station_metadata(args.station)

    station_meta = {
        'name': args.name.upper(),
        'wmo': extract_wmo_number(args.station),
    }
    if args.wban:
        station_meta['wban'] = args.wban
    if args.lat is not None:
        station_meta['lat'] = args.lat
    elif 'lat' in igra_meta:
        station_meta['lat'] = igra_meta['lat']
    if args.lon is not None:
        station_meta['lon'] = args.lon
    elif 'lon' in igra_meta:
        station_meta['lon'] = igra_meta['lon']
    if args.elev is not None:
        station_meta['elev'] = args.elev
    elif 'elev' in igra_meta:
        station_meta['elev'] = igra_meta['elev']

    lat = station_meta.get('lat', 0.0)
    lon = station_meta.get('lon', 0.0)
    elev = station_meta.get('elev', 0.0)
    print(f"  WMO:        {station_meta.get('wmo', '?')}")
    print(f"  Location:   {lat:.4f}, {lon:.4f}")
    print(f"  Elevation:  {elev:.0f} m")
    if igra_meta.get('station_name'):
        print(f"  Full name:  {igra_meta['station_name']}")
    print()

    # ---- Step 2: Download IGRA data ----
    if args.igra_file:
        igra_full_path = args.igra_file
        print(f"Step 2: Using existing IGRA file: {igra_full_path}")
    else:
        igra_full_path = os.path.join(args.outdir, f"{args.station}-data.txt")
        print("Step 2: Downloading IGRA data from NCEI")
        download_igra_data(args.station, igra_full_path)
    print()

    # ---- Step 3: Trim to requested years ----
    print(f"Step 3: Trimming to years {args.start_year}-{args.end_year}")
    igra_trimmed_path = os.path.join(
        args.outdir, f"{args.station}_{args.start_year}_{args.end_year}.txt"
    )
    stats = trim_igra_to_years(
        igra_full_path, igra_trimmed_path, args.start_year, args.end_year
    )
    print(f"  Total soundings in archive: {stats['total_soundings']}")
    print(f"  Soundings in range:         {stats['kept_soundings']}")
    print()

    if stats['kept_soundings'] == 0:
        print("ERROR: No soundings found in the requested year range.")
        print(f"  Check that station {args.station} has data for "
              f"{args.start_year}-{args.end_year}.")
        sys.exit(1)

    # ---- Step 4: Convert to FSL ----
    print("Step 4: Converting to FSL format")
    result = convert_igra_to_fsl_by_year(
        igra_trimmed_path, args.outdir, args.name, station_meta,
        args.start_year, args.end_year,
    )
    print(f"\r  Converted {result['combined_count']} soundings total")
    print()

    # ---- Step 5: Summary ----
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print()
    print("  Output files:")

    # Per-year files
    for year in sorted(result['year_counts'].keys()):
        yy = f"{year % 100:02d}"
        filename = f"{args.name.upper()}{yy}.rao"
        count = result['year_counts'][year]
        filepath = os.path.join(args.outdir, filename)
        size_kb = os.path.getsize(filepath) / 1024
        print(f"    {filename:20s}  {count:5d} soundings  ({size_kb:.0f} KB)")

    # Combined file
    if args.start_year != args.end_year:
        filename = os.path.basename(result['combined_path'])
        size_kb = os.path.getsize(result['combined_path']) / 1024
        print(f"    {filename:20s}  {result['combined_count']:5d} soundings  "
              f"({size_kb:.0f} KB)  [combined]")
    print()

    # ---- Cleanup ----
    if not args.keep_igra:
        for path in [igra_trimmed_path]:
            if os.path.exists(path):
                os.remove(path)
        if not args.igra_file and os.path.exists(igra_full_path):
            os.remove(igra_full_path)
        print("  Intermediate IGRA files cleaned up.")
        print("  (Use --keep-igra to retain them.)")
    else:
        print("  Intermediate IGRA files retained:")
        if not args.igra_file:
            print(f"    {igra_full_path}")
        print(f"    {igra_trimmed_path}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
