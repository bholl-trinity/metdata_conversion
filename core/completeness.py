"""
SFC file completeness assessment.

Parses AERMET .SFC output files to determine what percentage of hours
have valid (non-missing) meteorological data. Completeness is assessed
from the final SFC output — not from raw inputs — because validity of
a given hour depends on the combination of surface and upper air values.

Key rules:
  - Calm wind hours (zero wind speed) are NOT counted as missing
  - Missing-value sentinel codes indicate invalid hours
  - Completeness = valid_hours / total_hours × 100
"""

import calendar
import os


# SFC file format: fixed-width, one line per hour
# Key columns (approximate — varies by AERMET version):
#   Cols 1-2:   Year (2-digit)
#   Cols 3-4:   Month
#   Cols 5-6:   Day
#   Cols 7-8:   Julian day (3 digits sometimes)
#   Col  9-10:  Hour
#   ...various met parameters...
#
# The SFC format from AERMET is space-delimited with the following fields:
#   YR MO DY JDY HR  H0  U*  W*  DT/DZ ZICNV ZIMCH  M-O  Z0  BOWEN  ALBEDO
#   WSSPD WDIR  ZREF  HT  TTOP  TTREF  ...
#
# Missing value indicators:
#   -999.0 or -9.0 or -9 for various fields
#   The surface heat flux (H0) being -999.0 is a good indicator of a missing hour

# SFC fields (0-indexed after splitting on whitespace):
# 0=YR 1=MO 2=DY 3=JDAY 4=HR 5=H0(sensible heat flux) 6=U* 7=W* 8=DT/DZ
# 9=ZICNV 10=ZIMCH 11=M-O 12=Z0 13=BOWEN 14=ALBEDO
# 15=WSPD 16=WDIR 17=ZREF 18=HT 19=TTOP 20=TTREF

MISSING_VALUE = -999.0


def parse_sfc_file(sfc_path):
    """
    Parse an AERMET .SFC file into a list of hourly records.

    Returns list of dicts with year, month, day, jday, hour, and key met values.
    """
    records = []
    if not os.path.exists(sfc_path):
        return records

    with open(sfc_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 16:
                continue
            try:
                yr = int(parts[0])
                mo = int(parts[1])
                dy = int(parts[2])
                jday = int(parts[3])
                hr = int(parts[4])
                h0 = float(parts[5])      # sensible heat flux
                ustar = float(parts[6])   # friction velocity
                wstar = float(parts[7])   # convective velocity
                wspd = float(parts[15])   # wind speed
                wdir = float(parts[16])   # wind direction
            except (ValueError, IndexError):
                continue

            records.append({
                'year': yr,
                'month': mo,
                'day': dy,
                'jday': jday,
                'hour': hr,
                'h0': h0,
                'ustar': ustar,
                'wstar': wstar,
                'wspd': wspd,
                'wdir': wdir,
            })
    return records


def is_hour_valid(record):
    """
    Determine if an SFC hour is valid (not missing).

    An hour is valid if the sensible heat flux (H0) is not the missing
    value sentinel. Calm wind hours (wspd = 0) are explicitly valid.
    """
    h0 = record.get('h0', MISSING_VALUE)
    ustar = record.get('ustar', MISSING_VALUE)

    # Primary check: H0 (sensible heat flux) must not be missing
    if h0 <= MISSING_VALUE + 1:  # Close to -999
        return False

    # Secondary check: friction velocity
    if ustar <= MISSING_VALUE + 1:
        return False

    # Calm winds are valid — do NOT flag them as missing
    # (wspd == 0 is fine)

    return True


def compute_completeness(sfc_path, full_year=None):
    """
    Compute hourly data completeness from an SFC file.

    Args:
        sfc_path: Path to .SFC file
        full_year: If specified, compute against expected hours for that year
                   (handles leap years). Otherwise uses hours found in file.

    Returns dict with:
        total_hours: expected hours (8760 or 8784 for leap)
        valid_hours: hours with real data
        missing_hours: hours without valid data
        completeness_pct: percentage valid
        by_quarter: dict of Q1-Q4 completeness
        by_month: dict of month completeness
    """
    records = parse_sfc_file(sfc_path)

    if not records:
        year = full_year or 2020
        total = 8784 if calendar.isleap(year) else 8760
        return {
            'total_hours': total,
            'valid_hours': 0,
            'missing_hours': total,
            'completeness_pct': 0.0,
            'by_quarter': {f'Q{q}': 0.0 for q in range(1, 5)},
            'by_month': {m: 0.0 for m in range(1, 13)},
        }

    # Determine year from records
    year = records[0]['year']
    # Handle 2-digit year
    if year < 100:
        year += 2000 if year < 50 else 1900

    if full_year:
        year = full_year

    is_leap = calendar.isleap(year)
    total_hours = 8784 if is_leap else 8760

    # Quarter definitions (month ranges)
    quarters = {
        'Q1': (1, 2, 3),
        'Q2': (4, 5, 6),
        'Q3': (7, 8, 9),
        'Q4': (10, 11, 12),
    }

    # Count valid hours
    valid_total = 0
    valid_by_month = {m: 0 for m in range(1, 13)}
    hours_by_month = {m: 0 for m in range(1, 13)}

    # Expected hours per month
    expected_by_month = {}
    for m in range(1, 13):
        days = calendar.monthrange(year, m)[1]
        expected_by_month[m] = days * 24

    for rec in records:
        mo = rec['month']
        if 1 <= mo <= 12:
            hours_by_month[mo] += 1
            if is_hour_valid(rec):
                valid_total += 1
                valid_by_month[mo] += 1

    # Monthly completeness
    by_month = {}
    for m in range(1, 13):
        expected = expected_by_month[m]
        by_month[m] = round(valid_by_month[m] / expected * 100, 1) if expected else 0.0

    # Quarterly completeness
    by_quarter = {}
    for qname, months in quarters.items():
        q_expected = sum(expected_by_month[m] for m in months)
        q_valid = sum(valid_by_month[m] for m in months)
        by_quarter[qname] = round(q_valid / q_expected * 100, 1) if q_expected else 0.0

    completeness_pct = round(valid_total / total_hours * 100, 1) if total_hours else 0.0

    return {
        'total_hours': total_hours,
        'valid_hours': valid_total,
        'missing_hours': total_hours - valid_total,
        'completeness_pct': completeness_pct,
        'by_quarter': by_quarter,
        'by_month': by_month,
    }


def check_completeness(sfc_path, threshold, basis='quarterly', full_year=None):
    """
    Check whether an SFC file meets the completeness threshold.

    Args:
        sfc_path: Path to .SFC file
        threshold: Minimum completeness percentage (e.g., 90)
        basis: 'quarterly' or 'annual'
        full_year: Year for expected-hours calculation

    Returns dict with:
        passes: bool
        completeness: full completeness dict
        failures: list of strings describing what failed
    """
    comp = compute_completeness(sfc_path, full_year)
    failures = []

    if basis == 'quarterly':
        for qname, pct in comp['by_quarter'].items():
            if pct < threshold:
                failures.append(f'{qname}: {pct}% (threshold: {threshold}%)')
    else:
        if comp['completeness_pct'] < threshold:
            failures.append(
                f'Annual: {comp["completeness_pct"]}% (threshold: {threshold}%)')

    return {
        'passes': len(failures) == 0,
        'completeness': comp,
        'failures': failures,
    }
