#!/usr/bin/env python3
"""
igra_to_fsl.py

Convert IGRA v2 (Integrated Global Radiosonde Archive) upper air sounding
data to FSL (Forecast Systems Laboratory) format.

This is useful when you have IGRA data from NCEI but need FSL format for
tools like CPRAMMET or other processors that don't read IGRA natively.

Usage:
  python igra_to_fsl.py --input USM00072451-data.txt --output 72451.fsl

  # With station metadata overrides:
  python igra_to_fsl.py --input USM00072451-data.txt --output 72451.fsl \
      --wban 93734 --name IAD --lat 38.98 --lon -77.48 --elev 93.0

  # Filter to a specific date range:
  python igra_to_fsl.py --input USM00072451-data.txt --output 72451.fsl \
      --start 2020-01-01 --end 2020-12-31

IGRA v2 format reference:
  https://www.ncei.noaa.gov/pub/data/igra/data/igra2-data-format.txt

FSL format reference:
  Line types 254 (header), 1 (station ID), 2 (sounding checks),
  3 (station name/wind units), 4 (mandatory levels), 5 (significant levels),
  9 (surface level).
"""

import argparse
import sys
from datetime import datetime

# ============================================================================
# IGRA v2 FORMAT CONSTANTS
# ============================================================================

# Missing value codes in IGRA v2
IGRA_MISSING = -9999  # not available
IGRA_REMOVED = -8888  # removed by quality control

# IGRA v2 data record column positions (0-indexed Python slicing)
# Based on NCEI igra2-data-format.txt specification
#   Col  1:     LVLTYP1 (level type 1: 1=standard, 2=other, 3=wind-only)
#   Col  2:     LVLTYP2 (level type 2: 0=other, 1=surface, 2=tropopause)
#   Col  3-8:   ETIME   (elapsed time since launch, minutes*10; -9999=missing)
#   Col 10-15:  PRESS   (pressure, Pa; e.g., 100000 = 1000 hPa)
#   Col 16:     PFLAG   (pressure QC flag)
#   Col 17-21:  GPH     (geopotential height, meters)
#   Col 22:     ZFLAG   (GPH QC flag)
#   Col 23-27:  TEMP    (temperature, tenths of degrees C)
#   Col 28:     TFLAG   (temperature QC flag)
#   Col 29-33:  RH      (relative humidity, tenths of percent; -9999=missing)
#   Col 35-39:  DPDP    (dew point depression, tenths of degrees C)
#   Col 41-45:  WDIR    (wind direction, degrees from north)
#   Col 47-51:  WSPD    (wind speed, tenths of m/s)

# ============================================================================
# FSL FORMAT CONSTANTS
# ============================================================================

FSL_MISSING = 99999

# Mandatory pressure levels (hPa) recognized by FSL/AERMET
MANDATORY_LEVELS = [
    1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10
]


# ============================================================================
# IGRA PARSING
# ============================================================================

def parse_igra_header(line):
    """
    Parse an IGRA v2 header line (fixed-width format).

    Header format (1-indexed columns):
      Col  1:     '#' (header indicator)
      Col  2-12:  Station ID (e.g., USM00072451)
      Col 14-17:  Year
      Col 19-20:  Month
      Col 22-23:  Day
      Col 25-26:  Hour (99 = missing)
      Col 28-31:  Release time (hhmm, 9999 = missing)
      Col 33-36:  Number of levels
      Col 38-45:  P_SRC (pressure data source)
      Col 47-54:  NP_SRC (non-pressure data source)
      Col 56-62:  Latitude (10000ths of degrees, negative = south)
      Col 64-71:  Longitude (10000ths of degrees, negative = west)

    Returns dict or None if not a valid header.
    """
    if not line.startswith('#'):
        return None

    try:
        station_id = line[1:12].strip()
        year = int(line[13:17].strip())
        month = int(line[18:20].strip())
        day = int(line[21:23].strip())
        hour = int(line[24:26].strip())
        numlev = int(line[32:36].strip())

        # Release time (hhmm format, 9999 = missing)
        reltime_str = line[27:31].strip()
        reltime = int(reltime_str) if reltime_str and reltime_str != '9999' else None

        # Latitude and longitude (in 10000ths of degrees)
        lat_str = line[55:62].strip()
        lon_str = line[63:71].strip()
        lat = int(lat_str) / 10000.0 if lat_str else None
        lon = int(lon_str) / 10000.0 if lon_str else None

        return {
            'station_id': station_id,
            'year': year,
            'month': month,
            'day': day,
            'hour': hour,
            'reltime': reltime,
            'numlev': numlev,
            'lat': lat,
            'lon': lon,
        }
    except (ValueError, IndexError):
        return None


def parse_igra_data_line(line):
    """
    Parse an IGRA v2 data record (fixed-width format).

    Returns dict with parsed values, or None if line cannot be parsed.
    Values are returned in IGRA native units:
      - pres_pa:   pressure in Pa
      - gph_m:     geopotential height in meters
      - temp_10c:  temperature in tenths of degrees C
      - dpdp_10c:  dew point depression in tenths of degrees C
      - wdir_deg:  wind direction in degrees
      - wspd_10ms: wind speed in tenths of m/s
      - lvltyp1:   level type 1 (1=standard, 2=other, 3=wind-only)
      - lvltyp2:   level type 2 (0=other, 1=surface, 2=tropopause)
    """
    if len(line) < 51:
        return None

    try:
        lvltyp1 = int(line[0:1])
        lvltyp2 = int(line[1:2])
    except (ValueError, IndexError):
        return None

    def read_int(s, start, end):
        """Read an integer field, returning None for missing/removed values."""
        val_str = s[start:end].strip()
        if not val_str:
            return None
        val = int(val_str)
        if val == IGRA_MISSING or val == IGRA_REMOVED:
            return None
        return val

    return {
        'lvltyp1': lvltyp1,
        'lvltyp2': lvltyp2,
        'pres_pa': read_int(line, 9, 15),
        'gph_m': read_int(line, 16, 21),
        'temp_10c': read_int(line, 22, 27),
        'dpdp_10c': read_int(line, 34, 39),
        'wdir_deg': read_int(line, 40, 45),
        'wspd_10ms': read_int(line, 46, 51),
    }


def read_igra_soundings(input_path, start_date=None, end_date=None):
    """
    Read an IGRA v2 file and yield (header, levels) tuples.

    Each sounding is yielded as a tuple of (header_dict, [level_dicts]).
    Optionally filters to soundings within [start_date, end_date].
    """
    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        header = None
        levels = []

        for line in f:
            if line.startswith('#'):
                # Yield previous sounding if we have one
                if header is not None and levels:
                    yield header, levels

                header = parse_igra_header(line)
                levels = []
            else:
                if header is not None:
                    level = parse_igra_data_line(line)
                    if level is not None:
                        levels.append(level)

        # Yield last sounding
        if header is not None and levels:
            yield header, levels


def filter_by_date(soundings, start_date, end_date):
    """Filter soundings to those within the specified date range."""
    for header, levels in soundings:
        try:
            hour = header['hour'] if header['hour'] != 99 else 0
            dt = datetime(header['year'], header['month'], header['day'])
            if start_date and dt.date() < start_date:
                continue
            if end_date and dt.date() > end_date:
                continue
        except (ValueError, TypeError):
            continue
        yield header, levels


# ============================================================================
# FSL OUTPUT
# ============================================================================

def extract_wmo_number(station_id):
    """
    Extract the WMO station number from an IGRA station ID.

    IGRA IDs are formatted like 'USM00072451' where the WMO number
    is the digits after 'M000' (i.e., 72451).
    """
    # Try to extract digits after the country code prefix
    # Common patterns: USM00072451, RSM00027612, etc.
    import re
    match = re.search(r'M000(\d+)', station_id)
    if match:
        return match.group(1)
    # Fallback: just use the raw station ID digits
    digits = ''.join(c for c in station_id if c.isdigit())
    return digits if digits else '99999'


def classify_fsl_level(pres_hpa, is_surface=False):
    """
    Determine FSL line type for a pressure level.
    Returns 9 for surface, 4 for mandatory, 5 for significant.
    """
    if is_surface:
        return 9
    for mandatory in MANDATORY_LEVELS:
        if abs(pres_hpa - mandatory) < 0.5:
            return 4
    return 5


def write_fsl_sounding(outfile, header, levels, station_meta):
    """
    Write a single IGRA sounding in FSL format.

    Performs unit conversions from IGRA native units to FSL:
      - Pressure:  Pa → mb×10  (divide by 10)
      - Height:    meters (no conversion)
      - Temperature: tenths °C (no conversion, IGRA and FSL both use tenths °C)
      - Dew point: computed from temp - dew point depression (tenths °C)
      - Wind dir:  degrees (no conversion)
      - Wind speed: tenths m/s → knots (÷10 × 1.94384)
    """
    if not levels:
        return False

    # Filter out levels with no pressure (can't place them in a sounding)
    levels = [lev for lev in levels if lev['pres_pa'] is not None]
    if not levels:
        return False

    # Station metadata
    wban = station_meta.get('wban', '99999')
    wmo = station_meta.get('wmo', extract_wmo_number(header['station_id']))
    name = station_meta.get('name', header['station_id'][:14])
    lat = station_meta.get('lat') or header.get('lat') or 0.0
    lon = station_meta.get('lon') or header.get('lon') or 0.0
    elev = station_meta.get('elev', 0.0)

    # Date/time
    hour = header['hour'] if header['hour'] != 99 else 0
    day = header['day']
    month = header['month']
    year = header['year']

    # --- Type 254: Header line ---
    outfile.write(
        f"    254  {hour:5d}  {day:5d}  {month:5d}  {year:5d}                      \n"
    )

    # --- Type 1: Station ID line ---
    lat_100 = int(round(lat * 100))
    lon_100 = int(round(lon * 100))
    elev_int = int(round(elev))
    try:
        wban_int = int(wban)
    except (ValueError, TypeError):
        wban_int = 99999
    try:
        wmo_int = int(wmo)
    except (ValueError, TypeError):
        wmo_int = 99999
    outfile.write(
        f"      1{wban_int:7d}{wmo_int:7d}{lat_100:7d}{lon_100:7d}{elev_int:7d}       \n"
    )

    # --- Type 2: Sounding checks (all missing) ---
    outfile.write(
        f"      2{FSL_MISSING:7d}{FSL_MISSING:7d}{FSL_MISSING:7d}"
        f"{FSL_MISSING:7d}{FSL_MISSING:7d}       \n"
    )

    # --- Type 3: Station name and wind units ---
    outfile.write(
        f"      3          {name:<14s}                    kt\n"
    )

    # --- Data lines ---
    surface_written = False
    for lev in levels:
        pres_pa = lev['pres_pa']
        pres_hpa = pres_pa / 100.0

        # In FSL, only the first surface level gets type 9
        is_surface = (lev['lvltyp2'] == 1 and not surface_written)
        linetype = classify_fsl_level(pres_hpa, is_surface)
        if is_surface:
            surface_written = True

        # Pressure: Pa → mb×10 (i.e., divide by 10)
        pres_10 = int(round(pres_pa / 10.0))

        # Height: meters, direct
        height = lev['gph_m'] if lev['gph_m'] is not None else FSL_MISSING

        # Temperature: tenths of °C in both formats
        temp_10 = lev['temp_10c'] if lev['temp_10c'] is not None else FSL_MISSING

        # Dew point: IGRA gives dew point depression, FSL wants dew point
        if lev['temp_10c'] is not None and lev['dpdp_10c'] is not None:
            dewpt_10 = lev['temp_10c'] - lev['dpdp_10c']
        else:
            dewpt_10 = FSL_MISSING

        # Wind direction: degrees, direct
        wdir = lev['wdir_deg'] if lev['wdir_deg'] is not None else FSL_MISSING

        # Wind speed: tenths m/s → knots
        if lev['wspd_10ms'] is not None:
            wspd_ms = lev['wspd_10ms'] / 10.0
            wspd = int(round(wspd_ms * 1.94384))
        else:
            wspd = FSL_MISSING

        outfile.write(
            f"{linetype:7d}{pres_10:7d}{height:7d}{temp_10:7d}"
            f"{dewpt_10:7d}{wdir:7d}{wspd:7d}\n"
        )

    return True


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert IGRA v2 upper air data to FSL format"
    )
    parser.add_argument("--input", required=True,
                        help="Input IGRA v2 data file")
    parser.add_argument("--output", required=True,
                        help="Output FSL filename")
    parser.add_argument("--start", default=None,
                        help="Start date YYYY-MM-DD (optional)")
    parser.add_argument("--end", default=None,
                        help="End date YYYY-MM-DD (optional)")
    parser.add_argument("--wban", default=None,
                        help="WBAN station number (default: 99999)")
    parser.add_argument("--name", default=None,
                        help="Station name for FSL header (default: from IGRA ID)")
    parser.add_argument("--lat", type=float, default=None,
                        help="Station latitude (default: from IGRA header)")
    parser.add_argument("--lon", type=float, default=None,
                        help="Station longitude (default: from IGRA header)")
    parser.add_argument("--elev", type=float, default=None,
                        help="Station elevation in meters (default: 0)")

    args = parser.parse_args()

    start_date = None
    end_date = None
    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    # Build station metadata from CLI args
    station_meta = {}
    if args.wban:
        station_meta['wban'] = args.wban
    if args.name:
        station_meta['name'] = args.name
    if args.lat is not None:
        station_meta['lat'] = args.lat
    if args.lon is not None:
        station_meta['lon'] = args.lon
    if args.elev is not None:
        station_meta['elev'] = args.elev

    print("=" * 70)
    print("IGRA v2 to FSL Converter")
    print("=" * 70)
    print(f"Input:       {args.input}")
    print(f"Output:      {args.output}")
    if start_date:
        print(f"Start date:  {start_date}")
    if end_date:
        print(f"End date:    {end_date}")
    print("=" * 70)
    print()

    soundings = read_igra_soundings(args.input)

    if start_date or end_date:
        soundings = filter_by_date(soundings, start_date, end_date)

    success_count = 0
    skip_count = 0
    total_count = 0

    with open(args.output, 'w') as outfile:
        for header, levels in soundings:
            total_count += 1

            # Show first sounding's station info
            if total_count == 1:
                wmo = station_meta.get('wmo', extract_wmo_number(header['station_id']))
                lat = station_meta.get('lat') or header.get('lat') or 0.0
                lon = station_meta.get('lon') or header.get('lon') or 0.0
                print(f"Station:     {header['station_id']} (WMO {wmo})")
                print(f"Location:    {lat:.4f}N, {lon:.4f}E")
                print()

            wrote = write_fsl_sounding(outfile, header, levels, station_meta)
            if wrote:
                success_count += 1
            else:
                skip_count += 1

            if total_count % 100 == 0:
                sys.stdout.write(
                    f"\r  Processed {total_count} soundings, "
                    f"wrote {success_count}, skipped {skip_count}"
                )
                sys.stdout.flush()

    print(f"\r  Processed {total_count} soundings, "
          f"wrote {success_count}, skipped {skip_count}")
    print()
    print("=" * 70)
    print("COMPLETE")
    print(f"  Soundings written:  {success_count}")
    print(f"  Soundings skipped:  {skip_count}")
    print(f"  Output file:        {args.output}")
    print("=" * 70)

    if success_count == 0:
        print("\nWARNING: No soundings were written. Check input file and date range.")
        sys.exit(1)


if __name__ == "__main__":
    main()
