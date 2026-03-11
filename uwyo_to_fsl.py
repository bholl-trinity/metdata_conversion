#!/usr/bin/env python3
"""
uwyo_to_fsl.py

Download upper air sounding data from the University of Wyoming archive
and convert it to FSL (Forecast Systems Laboratory) format for use with
EPA's AERMET meteorological preprocessor.

Usage:
  python uwyo_to_fsl.py --station 72403 --start 1995-01-01 --end 2004-12-31 --output 72403_1995_2004.fsl

The script downloads 12Z soundings (the standard morning sounding used by AERMET)
for each day in the specified date range. It handles missing soundings gracefully
and writes all successfully retrieved soundings to a single FSL-format output file.

Note: The University of Wyoming server rate-limits requests. The script includes
a delay between requests to be respectful of the server. Downloading 10 years of
data will take roughly 1 hour at 1s delay.

Author: Generated for Brian at Trinity Consultants
Date: February 2026
"""

import argparse
import csv
import io
import os
import sys
import time
from datetime import datetime, timedelta

# ============================================================================
# Check for requests library
# ============================================================================

try:
    import requests
except ImportError:
    print("The 'requests' library is required. Install with: pip install requests")
    sys.exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Wyoming URL template for CSV data
UWYO_URL = (
    "https://weather.uwyo.edu/wsgi/sounding?"
    "datetime={year}-{month:02d}-{day:02d}+{hour:02d}:00:00"
    "&id={station}&type=TEXT:CSV"
)

# Default delay between requests in seconds
REQUEST_DELAY = 3.0

# FSL missing value
FSL_MISSING = 99999
FSL_MISSING_CLASSIC = 32767  # Pre-2000 FSL format missing value

# Mandatory pressure levels (hPa) used in FSL format
MANDATORY_LEVELS = [
    1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10
]

# Station metadata
STATION_INFO = {
    "72403": {"wban": "93734", "name": "IAD", "lat": 38.98, "lon": -77.48, "elev": 93.0},
}


# ============================================================================
# HELPERS
# ============================================================================

def knots_from_ms(speed_ms, missing=FSL_MISSING):
    """Convert m/s to knots."""
    if speed_ms is None:
        return missing
    return round(speed_ms * 1.94384)


def parse_csv_sounding(csv_text):
    """
    Parse Wyoming CSV sounding data into a list of level dictionaries.

    Returns list of dicts with keys:
        pres_hpa, height_m, temp_c, dewpt_c, wdir_deg, wspd_ms
    """
    levels = []
    reader = csv.reader(io.StringIO(csv_text.strip()))

    # Skip header line
    header = next(reader, None)
    if header is None:
        return levels

    for row in reader:
        if len(row) < 10:
            continue

        try:
            pres   = float(row[0].strip()) if row[0].strip() else None
            height = int(float(row[1].strip())) if row[1].strip() else None
            temp   = float(row[2].strip()) if row[2].strip() else None
            dewpt  = float(row[3].strip()) if row[3].strip() else None
            # Skip columns 4 (ice point), 5-6 (RH), 7 (mixing ratio)
            wdir   = int(float(row[8].strip())) if row[8].strip() else None
            wspd   = float(row[9].strip()) if row[9].strip() else None
        except (ValueError, IndexError):
            continue

        if pres is not None:
            levels.append({
                "pres_hpa": pres,
                "height_m": height,
                "temp_c":   temp,
                "dewpt_c":  dewpt,
                "wdir_deg": wdir,
                "wspd_ms":  wspd,
            })

    return levels


def classify_level(pres_hpa, is_surface=False):
    """
    Determine FSL line type for a given pressure level.
    Returns 9 for surface, 4 for mandatory, 5 for significant.
    """
    if is_surface:
        return 9

    for mandatory in MANDATORY_LEVELS:
        if abs(pres_hpa - mandatory) < 0.5:
            return 4

    return 5  # significant level


def write_fsl_sounding(outfile, levels, station_id, dt, station_meta, classic=False):
    """
    Write a single sounding in FSL format.

    If classic=True, uses pre-2000 missing value (32767) instead of 99999.
    """
    if not levels:
        return False

    missing = FSL_MISSING_CLASSIC if classic else FSL_MISSING

    wban = station_meta.get("wban", "99999")
    name = station_meta.get("name", station_id)
    lat  = station_meta.get("lat",  99.99)
    lon  = station_meta.get("lon",  999.99)
    elev = station_meta.get("elev", 9999.0)

    hour  = dt.hour
    day   = dt.day
    month = dt.month
    year  = dt.year

    # --- Header line (type 254) ---
    outfile.write(
        f"    254  {hour:5d}  {day:5d}  {month:5d}  {year:5d}                      \n"
    )

    # --- Station ID line (type 1) ---
    lat_100  = int(round(lat * 100))
    lon_100  = int(round(lon * 100))
    elev_int = int(round(elev))
    outfile.write(
        f"      1{int(wban):7d}{int(station_id):7d}{lat_100:7d}{lon_100:7d}{elev_int:7d}       \n"
    )

    # --- Sounding checks line (type 2) - leave blank ---
    outfile.write(
        f"      2{missing:7d}{missing:7d}{missing:7d}{missing:7d}{missing:7d}       \n"
    )

    # --- Station name and wind units line (type 3) ---
    outfile.write(
        f"      3          {name:<14s}                    kt\n"
    )

    # --- Data lines ---
    for i, lev in enumerate(levels):
        is_surface = (i == 0)
        linetype   = classify_level(lev["pres_hpa"], is_surface)

        pres_10  = int(round(lev["pres_hpa"] * 10)) if lev["pres_hpa"] is not None else missing
        height   = lev["height_m"]  if lev["height_m"]  is not None else missing
        temp_10  = int(round(lev["temp_c"]  * 10)) if lev["temp_c"]  is not None else missing
        dewpt_10 = int(round(lev["dewpt_c"] * 10)) if lev["dewpt_c"] is not None else missing
        wdir     = lev["wdir_deg"]  if lev["wdir_deg"]  is not None else missing
        wspd     = knots_from_ms(lev["wspd_ms"], missing)

        outfile.write(
            f"{linetype:7d}{pres_10:7d}{height:7d}{temp_10:7d}{dewpt_10:7d}{wdir:7d}{wspd:7d}\n"
        )

    return True


def download_sounding(station_id, dt, session):
    """
    Download a single sounding from the Wyoming archive.
    Returns CSV text or None if not available.
    """
    url = UWYO_URL.format(
        year=dt.year,
        month=dt.month,
        day=dt.day,
        hour=dt.hour,
        station=station_id,
    )

    try:
        response = session.get(url, timeout=30)

        if response.status_code == 200:
            text = response.text.strip()
            if "pressure_hPa" in text and len(text.split("\n")) > 2:
                return text
            else:
                return None
        else:
            return None
    except Exception as e:
        print(f"  Error downloading {dt}: {e}")
        return None


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Download Wyoming upper air data and convert to FSL format for AERMET"
    )
    parser.add_argument("--station", required=True, help="WMO station number (e.g., 72403)")
    parser.add_argument("--start",   required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end",     required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output",  required=True, help="Output FSL filename")
    parser.add_argument("--hour",    type=int, default=12,
                        help="Sounding hour in UTC (default: 12)")
    parser.add_argument("--both-hours", action="store_true",
                        help="Download both 00Z and 12Z soundings")
    parser.add_argument("--delay",   type=float, default=REQUEST_DELAY,
                        help=f"Delay between requests in seconds (default: {REQUEST_DELAY})")
    parser.add_argument("--wban",    default=None)
    parser.add_argument("--name",    default=None)
    parser.add_argument("--lat",     type=float, default=None)
    parser.add_argument("--lon",     type=float, default=None)
    parser.add_argument("--elev",    type=float, default=None)
    parser.add_argument("--resume",  action="store_true")

    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d")
    end_date   = datetime.strptime(args.end,   "%Y-%m-%d")

    # Build station metadata
    if args.station in STATION_INFO:
        station_meta = STATION_INFO[args.station].copy()
    else:
        station_meta = {"wban": "99999", "name": args.station,
                        "lat": 0.0, "lon": 0.0, "elev": 0.0}

    if args.wban: station_meta["wban"] = args.wban
    if args.name: station_meta["name"] = args.name
    if args.lat  is not None: station_meta["lat"]  = args.lat
    if args.lon  is not None: station_meta["lon"]  = args.lon
    if args.elev is not None: station_meta["elev"] = args.elev

    hours = [0, 12] if args.both_hours else [args.hour]

    total_days     = (end_date - start_date).days + 1
    total_requests = total_days * len(hours)

    print("=" * 70)
    print("Wyoming Upper Air to FSL Converter")
    print("=" * 70)
    print(f"Station:     {args.station} ({station_meta['name']})")
    print(f"Location:    {station_meta['lat']:.2f}N, {station_meta['lon']:.2f}E")
    print(f"Elevation:   {station_meta['elev']:.0f} m")
    print(f"Period:      {args.start} to {args.end}")
    print(f"Hours (UTC): {hours}")
    print(f"Output:      {args.output}")
    print(f"Total requests: ~{total_requests}")
    est_time = total_requests * args.delay / 3600
    print(f"Estimated time: ~{est_time:.1f} hours at {args.delay}s delay")
    print("=" * 70)
    print()

    mode = "a" if args.resume else "w"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "AERMET-FSL-Converter/1.0 (air quality research)"
    })

    success_count = 0
    fail_count    = 0

    with open(args.output, mode) as outfile:
        current_date = start_date

        while current_date <= end_date:
            for hour in hours:
                dt = current_date.replace(hour=hour)

                progress = ((current_date - start_date).days * len(hours)) + hours.index(hour)
                pct = (progress / total_requests) * 100 if total_requests > 0 else 0

                sys.stdout.write(
                    f"\r[{pct:5.1f}%] {dt.strftime('%Y-%m-%d %HZ')} - "
                    f"OK: {success_count}, Missing: {fail_count}"
                )
                sys.stdout.flush()

                csv_text = download_sounding(args.station, dt, session)

                if csv_text:
                    levels = parse_csv_sounding(csv_text)
                    if levels and len(levels) >= 3:
                        wrote = write_fsl_sounding(
                            outfile, levels, args.station, dt, station_meta
                        )
                        if wrote:
                            success_count += 1
                        else:
                            fail_count += 1
                    else:
                        fail_count += 1
                else:
                    fail_count += 1

                time.sleep(args.delay)

            current_date += timedelta(days=1)

    print()
    print()
    print("=" * 70)
    print("COMPLETE")
    print(f"  Soundings written:  {success_count}")
    print(f"  Soundings missing:  {fail_count}")
    print(f"  Output file:        {args.output}")
    print("=" * 70)

    if success_count == 0:
        print("\nWARNING: No soundings were retrieved. Check station number and date range.")


if __name__ == "__main__":
    main()
