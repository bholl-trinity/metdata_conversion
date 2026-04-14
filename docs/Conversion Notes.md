# GHCNh Format Converter - Conversion Notes

This document describes known differences between the GHCNh source format and the output formats, and explains design decisions made in the converter.

The converter supports two output formats:
- **ISD (Integrated Surface Data)** - Variable-length fixed-width format used by NCEI
- **CD144 (.met)** - Fixed-width format (79 chars/line) used for AERMOD/ISC meteorological input
 
---
 
## Cloud Cover Data (GA, GD, GE, GF sections)
 
### What we output: GA only
 
The converter outputs **GA (Sky Cover Layer)** records derived from the GHCNh sky cover columns along with their corresponding base heights. Up to **four** GA records (GA1–GA4) are emitted per observation, one per reported layer.

### GHCNh sky cover column schemas

Two column-name schemas have been observed in GHCNh PSV exports:

**Older exports (3 layers):**
- `sky_cover_1`, `sky_cover_2`, `sky_cover_3` — coverage codes (e.g. `FEW:02`, `SCT:04`, `OVC:08`)
- `sky_cover_baseht_1/2/3` — base heights in meters

**Newer exports (4 layers, split into two column families):**
- `sky_cover_layer_1..4` + `sky_cover_layer_baseht_1..4` — carry SYNOP-style ceiling data (height only, no coverage code)
- `sky_cover_summation_1..4` + `sky_cover_summation_baseht_1..4` — carry METAR/SPECI layer observations (coverage + height)

In newer files the two families are **complementary, not redundant**: for any given observation, the cloud data typically lives in exactly one of them. METAR/SPECI records populate `sky_cover_summation_*`; SYNOP records populate only `sky_cover_layer_baseht_*` (no coverage code, just a ceiling height).

The converter normalizes these aliases at parse time (`normalizeSkyCoverAliases` in `ghcnh-to-isd.js`) onto canonical `sky_cover_N` / `sky_cover_baseht_N` keys, preferring `sky_cover_summation_*` over `sky_cover_layer_*` when both are populated. Downstream code reads only the canonical names, so output is identical regardless of input vintage.

> **Why this matters:** Before the aliasing was added, newer GHCNh files appeared to have empty sky cover in every record (the old `sky_cover_N` columns no longer exist), causing the "empty sky cover = clear" fallback to fire for every hour. When that output was fed to AERMET, every hour became 0/8ths cloud cover.
 
### What we intentionally DO NOT output: GD, GE, GF
 
The following cloud-related sections are **intentionally omitted** from the output:
 
- **GD** (Sky Cover Summation State) - Cumulative sky coverage at each layer
- **GE** (Sky Condition Observation) - Additional sky condition details
- **GF** (Sky Condition Summary) - Total sky cover and cloud genus information
 
### Why
 
Legacy ISHD files contained GD, GE, and GF sections with derived and supplementary cloud data that came from additional data sources or was calculated from raw observations. However, the GHCNh format only provides observed cloud layer data, which corresponds to the GA section in ISHD.
 
Since we cannot accurately reproduce GD, GE, or GF records from the available GHCNh source data, these sections are intentionally omitted rather than generating potentially incorrect derived values.
 
### Important
 
**Do not attempt to generate GD, GE, or GF records.** Any apparent "mismatch" with legacy ISHD example files for these sections is expected and correct behavior.

## Sky Cover Fill for FM-12 SYNOP Records

FM-12 SYNOP reports typically have blank `sky_cover` fields, which can cause problems for downstream programs that consume the ISD output. To address this, the converter includes a preprocessing step that fills in missing sky cover data.

**How it works:**
- When a record has empty `sky_cover_1`, the converter looks back through previous observations from the same station
- If a record with valid sky cover data is found within the previous 45 minutes, its sky cover fields are copied to the current record
- All sky cover fields are copied: `sky_cover_1/2/3`, `sky_cover_baseht_1/2/3`, and their associated metadata fields
- If no valid sky cover is found within 45 minutes, the record retains the missing value codes (coverage=99)

**Why 45 minutes?**
- METAR reports are typically issued hourly (at :54 past the hour)
- SYNOP reports are issued every 3 hours (at :00)
- A 45-minute window ensures that the most recent METAR before a SYNOP will be used if available

## Empty Sky Cover Handling

Some weather stations leave the `sky_cover_1/2/3` fields blank when skies are clear, rather than explicitly recording a clear sky value like `CLR:00`. To ensure these records have proper sky cover data in the output, the converter treats empty sky cover as clear sky.

**How it works:**
- Before processing sky cover fields, the converter checks if all `sky_cover_1`, `sky_cover_2`, and `sky_cover_3` fields (and their base heights) are empty
- If all sky cover fields are empty, the converter outputs a GA1 record indicating clear skies: `GA1005+999999999`
  - `00` = 0/8ths cloud cover (clear)
  - `5` = Quality code (passed all QC)
  - `+99999` = Missing height (not applicable for clear sky)
- If any sky cover field has data, normal processing is used to convert to GA1/GA2/GA3

**Why this matters:**
- Without this handling, records with empty sky cover would have no GA section in the output
- This ensures all records have meaningful sky cover data for downstream consumers

---

## CD144 Output Format

The CD144 format is a fixed-width text format (79 characters per line) commonly used as meteorological input for AERMOD and ISC air dispersion models. Each line represents one hour of data, and a complete file contains every hour of a single year (8760 lines, or 8784 for leap years).

### Time Zone Conversion

GHCNh data is in UTC. CD144 output uses **local standard time**. The user provides a UTC offset (e.g., -5 for US Eastern Standard Time). No automatic daylight saving time adjustment is applied.

When the UTC-to-local shift moves an observation across a year boundary (e.g., UTC Jan 1 00:00 with offset -5 becomes Dec 31 19:00 of the previous year), the converter generates separate output files for each year.

### Hourly Assignment

GHCNh observations have specific minute values (e.g., :54 for METAR, :00 for SYNOP). The converter assigns each observation to the hour of its local time. When multiple observations fall in the same local hour, the one with the highest minute value is preferred (closest to the end of the hour). This prioritizes METAR observations (:54) over SYNOP (:00) when both exist for the same hour.

Hours with no matching observation produce a line with the station ID and date/time filled in but all data fields blank.

### Unit Conversions

| Field | GHCNh Unit | CD144 Unit | Conversion |
|-------|-----------|------------|------------|
| Temperature | Celsius | Whole degrees Fahrenheit | F = C x 9/5 + 32, rounded |
| Dewpoint | Celsius | Whole degrees Fahrenheit | Same as temperature |
| Wind speed | m/s | Knots | knots = m/s x 1.94384, rounded |
| Wind direction | Degrees (0-360) | Nearest 10 degrees / 10 | e.g., 340 degrees -> 34 |
| Station pressure | hPa | inHg x 100 | inHg100 = hPa x 2.953, rounded |
| Ceiling height | Meters | Feet / 100 | ft100 = meters x 3.28084 / 100, rounded |

### Negative Temperature Convention

Negative Fahrenheit values use an "X" prefix instead of a minus sign. For example, -4 degrees F is written as `X04`. Values are clamped to a minimum of -99 degrees F (`X99`). A temperature of exactly 0 degrees F is written as `  0` (space-padded), not `X00`.

### Cloud Cover

Total cloud cover is derived from the maximum oktas value across all cloud layers (sky_cover_1, sky_cover_2, sky_cover_3) and converted to tenths:

| Oktas | Tenths | CD144 Value |
|-------|--------|-------------|
| 0 (CLR) | 0 | `0` |
| 1 (FEW) | 1 | `1` |
| 2 (FEW) | 3 | `3` |
| 3 (SCT) | 4 | `4` |
| 4 (SCT) | 5 | `5` |
| 5 (BKN) | 6 | `6` |
| 6 (BKN) | 8 | `8` |
| 7 (BKN) | 9 | `9` |
| 8 (OVC) | 10 | `-` |

VV (vertical visibility) is treated as equivalent to OVC (8 oktas).

### Ceiling Height

The ceiling is the height of the lowest BKN, OVC, or VV cloud layer. If only FEW or SCT layers are present (no ceiling), the field is left blank. The height is converted from meters to feet and divided by 100.

### Relative Humidity

The converter uses the `relative_humidity` field from GHCNh when available. If missing, it calculates RH from temperature and dewpoint using the Magnus formula.

### Station ID

The 5-digit station identifier in columns 1-5 is the first 5 characters of the 6-digit USAF station ID (e.g., USAF 725190 becomes 72519). If no USAF ID can be extracted from the source data, it defaults to 99999.

### Wind Direction for Calm Winds

When wind is calm (measurement code includes "C-Calm"), the wind direction field is set to `00` and wind speed to `00`.

