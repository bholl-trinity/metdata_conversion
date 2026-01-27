# GHCNh to ISHD Conversion Notes
 
This document describes known differences between the GHCNh source format and the ISHD output format, and explains design decisions made in the converter.
 
---
 
## Cloud Cover Data (GA, GD, GE, GF sections)
 
### What we output: GA only
 
The converter outputs **GA (Sky Cover Layer)** records derived from the GHCNh `sky_cover_1`, `sky_cover_2`, and `sky_cover_3` fields along with their corresponding base heights.
 
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

