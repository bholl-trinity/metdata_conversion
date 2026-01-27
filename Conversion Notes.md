# GHCNh to ISD Conversion Notes

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
