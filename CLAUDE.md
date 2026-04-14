# CLAUDE.md — Project Context for AI Assistants

> **Purpose of this file:** This is a comprehensive knowledge transfer document.
> Read this file first to understand the entire repository before making any changes.

---

## Project Identity

**Name:** metdata_conversion (meteorological data conversion toolkit)
**Owner:** bholl-trinity
**Primary language:** Python (CLI tools + Flask GUI), JavaScript (browser converters)
**Domain:** EPA air quality dispersion modeling — preparing meteorological input
files for EPA's AERMET/AERMOD modeling system.

> **History note:** This repo previously contained a full AERMET automation tool
> (Python `aermet/` + Rust `aermet-tool/` rewrite). Those were moved to their own
> dedicated repository in commit `37cd640` (2026-03-31). What remains here is the
> collection of format-conversion tools and upper-air CLI utilities.

---

## What This Project Does

This toolkit provides focused format-conversion utilities for AERMOD modelers:

1. Convert NCEI GHCNh data to ISD (for AERMET ingestion) or CD144 (for AERMOD/ISC)
2. Gap-fill CD144 files
3. Convert CD144 to HUSWO
4. Convert upper-air soundings (IGRA, University of Wyoming) to FSL format

**Key insight:** AERMET doesn't yet support the modern GHCNh format from NCEI.
The browser-based GHCNh -> ISD converter bridges that gap. When EPA updates
AERMET to read GHCNh natively, that converter can be retired.

---

## Repository Structure

```
metdata_conversion/
├── CLAUDE.md                          # THIS FILE - read first
├── README.md                          # User-facing overview
├── .gitignore                         # Ignores: *.fsl, *.log, __pycache__, gui/output/
├── .github/workflows/pages.yml        # GitHub Pages deployment (for app/)
│
├── app/                               # PRIMARY: Browser-based converters (GitHub Pages)
│   ├── index.html                     # UI with file drop zone
│   ├── converter.js                   # Event handlers, UI orchestration
│   ├── ghcnh-to-isd.js                # GHCNh PSV -> ISD fixed-width (~33KB)
│   ├── ghcnh-to-cd144.js              # GHCNh PSV -> CD144 (~16KB)
│   ├── gap-fill.html                  # CD144 gap-filling tool
│   ├── cd144-to-huswo.html            # CD144 -> HUSWO converter
│   └── launch.bat                     # Windows launcher (opens index.html)
│
├── gui/                               # Flask wrapper for CLI upper-air tools
│   ├── server.py                      # Imports igra_to_fsl/igra_fsl_tool/uwyo_to_fsl
│   ├── static/                        # Gap-fill HTML/CSS
│   └── output/                        # Generated files (gitignored)
│
├── igra_to_fsl.py                     # CLI: IGRA v2 -> FSL format
├── igra_fsl_tool.py                   # CLI: Download IGRA by call sign + convert to FSL
├── uwyo_to_fsl.py                     # CLI: Wyoming upper air -> FSL
├── "IGRA to FSL Converter.bat"        # Windows launcher for the Flask gap-fill UI
│
├── docs/                              # Design & reference documentation
│   ├── Conversion Notes.md            # AUTHORITATIVE format conversion reference
│   ├── ghcnh_DOCUMENTATION.rtf        # NCEI GHCNh format spec
│   ├── isd-format-document.rtf        # NCEI ISD format spec
│   ├── aermet-automation-plan.md      # Historical: design spec for the removed aermet/ tool
│   └── rust-rewrite-plan.md           # Historical: Rust port plan for the removed aermet-tool/
│
└── samples/                           # Test/example data files
    ├── KSYR_*.psv                     # GHCNh sample files
    ├── *.ish, *.met, *.rao            # Converted format examples
    └── ISH and CD144 sample KSYR/     # Real-world worked examples
```

---

## The Two Main Components

### 1. Browser Converters (`app/` — JavaScript, deployed to GitHub Pages)

Vanilla HTML/JS/CSS (no framework, no build step) that runs entirely client-side.
Deployed to GitHub Pages via `.github/workflows/pages.yml`. Four tools:

- **GHCNh -> ISD** (`ghcnh-to-isd.js`) — primary converter
- **GHCNh -> CD144** (`ghcnh-to-cd144.js`)
- **CD144 gap-fill** (`gap-fill.html`)
- **CD144 -> HUSWO** (`cd144-to-huswo.html`)

### 2. Upper-Air CLI Tools + Flask GUI (`gui/` wraps the root `*.py` scripts)

The three root-level Python scripts are the engines; `gui/server.py` imports
them and exposes a simple Flask UI. Launch via `"IGRA to FSL Converter.bat"`
or `python gui/server.py` (opens http://localhost:5001).

- `igra_to_fsl.py` — IGRA v2 -> FSL, with date range filtering & metadata overrides
- `igra_fsl_tool.py` — Look up IGRA station from 3-letter call sign, download, convert
  - Auto-looks up WBAN from ISD history CSV (as of commit 37cd640)
- `uwyo_to_fsl.py` — Download 12Z soundings from U. Wyoming (rate-limited, 3s/request)

**Dependencies:** flask, requests, certifi

---

## Critical Domain Knowledge

### Data Sources & Formats
| Source | Format | Used For | Notes |
|--------|--------|----------|-------|
| GHCNh | Pipe-separated values (PSV) | Surface observations | From NCEI |
| ISD (ISHD) | Fixed-width (variable length) | AERMET surface input | Converted from GHCNh |
| CD144 | Fixed-width, 79 chars/line | AERMOD/ISC surface input | Converted from GHCNh |
| HUSWO | Fixed-width | Alternative surface format | Converted from CD144 |
| IGRA v2 | Fixed-width text | Upper air soundings | From NCEI |
| FSL | Fixed-width text | Upper air (AERMET-compatible) | Converted from IGRA or Wyoming |

### GHCNh -> ISD Conversion (the core algorithm)

This is the most complex code in the repo. It lives in `app/ghcnh-to-isd.js`.
See `docs/Conversion Notes.md` for the authoritative spec. Key rules:

1. **Cloud cover: GA only, up to 4 layers** — Only output GA (Sky Cover Layer)
   records, GA1-GA4. Do NOT generate GD/GE/GF records. GHCNh only has raw
   observations, not derived layers. See `Conversion Notes.md:11-33`.

2. **GHCNh sky cover column aliases** — Newer GHCNh exports split the old
   `sky_cover_N` columns into two families: `sky_cover_summation_N` (METAR
   observations — coverage + height) and `sky_cover_layer_N` (SYNOP ceiling
   heights — height only, no coverage). These are complementary, not
   redundant. `parseGHCNh` coalesces both families onto canonical
   `sky_cover_N` / `sky_cover_baseht_N` keys via `normalizeSkyCoverAliases`.
   **Missing this aliasing causes every output hour to fall back to
   clear-sky (0 oktas),** which is what AERMET then reports as "all zero
   cloud cover." See `Conversion Notes.md` sky cover section.

3. **SYNOP sky cover fill** — FM-12 SYNOP reports often have blank sky cover.
   The converter looks back up to 45 minutes for valid sky cover from the same
   station. See `Conversion Notes.md:35-48`.

4. **Empty sky cover = clear** — If all `sky_cover_1/2/3/4` are empty (not
   explicitly "CLR"), output `GA1005+999999999` (0/8ths clear, quality=5,
   missing height).

5. **Okta mapping** — CLR/`:00`→00, FEW→01-02, SCT→03-04, BKN→05-07, OVC→08.
   VV (vertical visibility) is treated as 8 oktas for ceiling purposes.

6. **Year range + UTC offset padding** (added in 37cd640) — Converter accepts
   a year range and UTC offset. Output includes the full UTC year *plus* extra
   hours from the adjacent year so AERMET has complete data once converted to
   local standard time. Western hemisphere pads the end; eastern hemisphere
   pads the start. Leave the year blank to convert the entire file.

7. **Negative Fahrenheit** — Temps below 0F use "X" prefix: -4F -> `X04`.
   Clamped to -99F (`X99`). Zero is space-padded (`  0`).

8. **Calm wind direction** — When wind speed is 0 or code includes "C-Calm",
   direction is `00` (not 360 or missing).

9. **Unit conversions:**
   - Temperature: C -> F (with rounding rules)
   - Wind speed: m/s -> knots
   - Pressure: Pa -> hPa (divide by 100)
   - Cloud base height: meters (no conversion needed for GA)
   - Cloud cover: oktas (0-8 scale)

10. **Hourly assignment** — Observations are assigned to local hours. Prefers
    METAR over SYNOP when both exist for the same hour.

11. **RH calculation** — If the relative humidity field is empty, calculate
    from dewpoint temperature using the Magnus formula.

### GHCNh -> CD144 Conversion

Separate implementation in `app/ghcnh-to-cd144.js`. Fixed-width 79 chars/line,
8760 lines/year (8784 for leap years). See `Conversion Notes.md:68+`. Notable:

- **No daylight saving time** — uses a fixed UTC offset provided by the user.
- **Year-boundary crossings** — if the UTC-to-local shift moves a record
  across a year boundary, separate output files are generated per year.
- **Hourly selection** — within a local hour, prefer the observation with the
  highest minute value (METAR :54 beats SYNOP :00).
- **Ceiling** — lowest BKN/OVC/VV layer. FEW/SCT only -> ceiling blank; cloud
  cover present but no ceiling -> 22000 (unlimited).

### IGRA -> FSL Conversion
- Parses IGRA v2 fixed-width format; FSL line types 254, 1, 2, 3, 4, 5, 6, 7, 9.
- `igra_fsl_tool.py` auto-downloads by 3-letter call sign (e.g., "DTX"),
  trims by year, writes per-year and combined output files.
- **WBAN auto-lookup** (37cd640): type-1 headers look up WBAN from ISD history
  CSV instead of writing 99999. `--wban` still overrides manually.

---

## Important Gotchas & Quirks

1. **No unit tests exist.** Highest-value candidates if adding tests: GHCNh
   parsing edge cases, unit conversions, IGRA year trimming, SYNOP sky-cover
   backfill window.

2. **GHCNh -> ISD lives only in JavaScript now.** The Python and Rust parallel
   implementations were removed with the `aermet/` and `aermet-tool/` trees in
   commit 37cd640. If logic changes, there's only one place to change:
   `app/ghcnh-to-isd.js`.

3. **SSL/TLS fallback chain** (Python side) — HTTP client tries certifi ->
   system default -> unverified (with warning). Handles machines with
   outdated CA bundles.

4. **CD144 time zone: NO daylight saving time** — Uses fixed UTC offset
   provided by user. If the offset moves a record across a year boundary,
   separate output files are generated per year.

5. **GHCNh station list is fixed-width** — Specific column positions. Must
   strip leading zeros correctly.

6. **Large file handling** — GHCNh downloads can be 100+ MB. Python side uses
   streaming (`iter_content(chunk_size=65536)`) with progress callbacks.
   Browser side processes directly from the drop-zone File object.

7. **`app/` deploys to GitHub Pages** via `.github/workflows/pages.yml`. Any
   change there ships the next time `main` is pushed.

8. **Windows batch files** handle Python-not-on-PATH gracefully with
   `where python` checks.

9. **University of Wyoming rate limiting** — `uwyo_to_fsl.py` sleeps 3s
   between requests. Don't remove this; it's there to be a good citizen.

10. **Historical docs in `docs/`** — `aermet-automation-plan.md` and
    `rust-rewrite-plan.md` describe tooling that no longer lives in this repo
    (moved to a dedicated repo). They are retained for reference but are not
    actionable against this codebase.

---

## Development Patterns

### Frontend (app/)
- Vanilla HTML/JS/CSS. No framework. No build step. No package.json.
- Files are loaded as plain `<script>` tags from `index.html`.
- Each converter exposes functions on `window` that `converter.js` calls.

### Python (root + gui/)
- Each root script is standalone and usable from the CLI or imported.
- `gui/server.py` imports from the root scripts — the Flask layer is a thin
  wrapper, not a reimplementation.
- No ORM, no database; outputs go to `gui/output/` (gitignored).

---

## Git & CI
- **Default branch:** `main`
- **CI:** GitHub Pages deployment only (`.github/workflows/pages.yml`)
- **No automated tests in CI** (no tests exist)
- **.gitignore:** `*.fsl`, `*.log`, `__pycache__/`, `*.pyc`, `gui/output/`

---

## Key Documentation Files

Read these for deep dives:
- **`docs/Conversion Notes.md`** — THE authoritative reference for every format
  conversion and edge case. Read this before touching any converter.
- **`docs/ghcnh_DOCUMENTATION.rtf`** — NCEI's GHCNh format spec (source of truth
  for field names and codes).
- **`docs/isd-format-document.rtf`** — NCEI's ISD/ISHD format spec.
- **`docs/aermet-automation-plan.md`** / **`docs/rust-rewrite-plan.md`** —
  Historical. Describe tooling now in a separate repo. Do not use as a guide
  for work in this repo.

---

## Common Tasks

### Modifying GHCNh -> ISD conversion
1. **Read `docs/Conversion Notes.md` first** — it documents every edge case.
2. Edit `app/ghcnh-to-isd.js`.
3. Test with sample files in `samples/` (especially `KSYR_*.psv` + the
   `ISH and CD144 sample KSYR/` worked examples).
4. Pushing to `main` deploys the change to GitHub Pages automatically.

### Modifying GHCNh -> CD144 conversion
1. Read `docs/Conversion Notes.md` (CD144 section, from ~line 68).
2. Edit `app/ghcnh-to-cd144.js`.
3. Test with `samples/CD144/` worked examples.

### Adding/changing an upper-air CLI tool
1. Edit the relevant root script (`igra_to_fsl.py`, `igra_fsl_tool.py`,
   or `uwyo_to_fsl.py`).
2. If the Flask GUI needs the new capability, update `gui/server.py`
   (it imports from the root scripts — no duplication).
3. Test from CLI first, then through the GUI.
