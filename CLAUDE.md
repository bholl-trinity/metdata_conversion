# CLAUDE.md — Project Context for AI Assistants

> **Purpose of this file:** This is a comprehensive knowledge transfer document.
> Read this file first to understand the entire repository before making any changes.

---

## Project Identity

**Name:** metdata_conversion (meteorological data conversion toolkit)
**Owner:** bholl-trinity
**Primary language:** Python (stable), Rust (in-progress rewrite)
**Domain:** EPA air quality dispersion modeling — specifically, preparing meteorological
input files for EPA's AERMET/AERMOD modeling system.

---

## What This Project Does

This toolkit helps EPA AERMOD air dispersion modelers prepare meteorological input
files. It automates the complex workflow of:

1. Discovering nearby weather stations (surface + upper air)
2. Downloading meteorological data from NOAA/NCEI
3. Converting between formats (GHCNh -> ISD, IGRA -> FSL, etc.)
4. Running EPA preprocessing utilities (AERMET, AERSURFACE, AERMINUTE)
5. Assessing data completeness
6. Producing production-ready .SFC and .PFL files for AERMOD

**Key insight:** AERMET doesn't yet support the modern GHCNh format from NCEI.
This tool bridges that gap by converting GHCNh to ISD format automatically.
When EPA updates AERMET to read GHCNh natively, the conversion step can be removed.

---

## Repository Structure

```
metdata_conversion/
├── CLAUDE.md                          # THIS FILE - read first
├── .gitignore                         # Ignores: *.fsl, *.log, __pycache__, gui/output/
├── .github/workflows/pages.yml        # GitHub Pages deployment (for app/)
│
├── aermet/                            # PRIMARY: Python/Flask AERMET automation tool
│   ├── server.py                      # Flask app - REST API + serves UI
│   ├── launch.bat                     # Windows launcher (checks Python, installs deps)
│   ├── requirements.txt               # flask, requests, certifi
│   ├── README.md                      # User-facing documentation
│   ├── core/                          # Backend modules
│   │   ├── geocode.py                 # Address/airport/lat-lon -> coordinates
│   │   ├── stations.py                # Station discovery (GHCNh, ISD, IGRA from NCEI)
│   │   ├── download.py                # Data download orchestration
│   │   ├── ghcnh_to_isd.py            # GHCNh PSV -> ISD fixed-width converter
│   │   ├── igra.py                    # IGRA download, parse, trim by year
│   │   ├── http.py                    # Shared HTTP client with SSL fallback
│   │   ├── project.py                 # Project workspace management (UUID dirs)
│   │   ├── completeness.py            # SFC file quality assessment
│   │   ├── aermet_runner.py           # AERMET control file generation + execution
│   │   ├── aersurface.py              # AERSURFACE control file + execution
│   │   ├── aerminute.py               # AERMINUTE 1-minute wind processing
│   │   └── __init__.py
│   ├── static/                        # Frontend (HTML/JS/CSS wizard UI)
│   ├── data/                          # Cached station inventories (auto-downloaded)
│   └── projects/                      # Per-run working directories
│
├── aermet-tool/                       # SECONDARY: Rust rewrite (in progress)
│   ├── Cargo.toml                     # axum, tokio, reqwest, rust-embed, serde, etc.
│   ├── src/                           # Direct port of Python modules to Rust
│   │   ├── main.rs                    # Entry: port discovery, browser launch
│   │   ├── server.rs                  # HTTP routes (axum) - largest file ~28KB
│   │   ├── ghcnh_to_isd.rs            # GHCNh converter (~25KB)
│   │   ├── aermet_runner.rs           # Control file gen + subprocess
│   │   ├── stations.rs                # Station discovery
│   │   ├── completeness.rs            # SFC parsing
│   │   ├── download.rs                # Download orchestration
│   │   ├── geocode.rs                 # Geocoding
│   │   ├── project.rs                 # Project state (JSON)
│   │   ├── aersurface.rs              # AERSURFACE logic
│   │   ├── aerminute.rs               # AERMINUTE logic
│   │   ├── igra.rs                    # IGRA handling
│   │   └── http_client.rs             # Shared reqwest client
│   ├── static/                        # Embedded frontend (same UI)
│   └── data/                          # Embedded airports.csv
│
├── app/                               # LEGACY: Client-side converter (GitHub Pages)
│   ├── index.html                     # UI with file drop zone
│   ├── converter.js                   # Event handlers, UI orchestration
│   ├── ghcnh-to-isd.js               # JS version of GHCNh->ISD (~33KB)
│   ├── ghcnh-to-cd144.js             # GHCNh->CD144 format (~16KB)
│   ├── gap-fill.html                  # CD144 gap-filling tool
│   └── cd144-to-huswo.html            # CD144->HUSWO converter
│
├── gui/                               # Legacy Flask UI for gap-fill tool
│   ├── server.py                      # Simple Flask server
│   └── static/                        # Gap-fill HTML/CSS
│
├── igra_to_fsl.py                     # CLI: IGRA v2 -> FSL format (815 lines)
├── igra_fsl_tool.py                   # CLI: Download IGRA + convert to FSL (596 lines)
├── uwyo_to_fsl.py                     # CLI: Wyoming upper air -> FSL (357 lines)
├── "IGRA to FSL Converter.bat"        # Windows launcher for gap-fill tool
│
├── docs/                              # Design & reference documentation
│   ├── Conversion Notes.md            # AUTHORITATIVE format conversion reference
│   ├── aermet-automation-plan.md      # Full design spec for aermet/ tool
│   └── rust-rewrite-plan.md           # Rust port strategy & milestones
│
└── samples/                           # Test/example data files
    ├── KSYR_*.psv                     # GHCNh sample files
    ├── *.ish, *.met, *.rao            # Converted format examples
    └── ISH and CD144 sample KSYR/     # Real-world worked examples
```

---

## The Two Main Components

### 1. AERMET Automation Tool (`aermet/` — Python, stable)

A locally-run Flask web app with a 6-step wizard UI:

1. **Location** — Enter address, lat/lon, or airport code
2. **Stations** — Discover & select surface (GHCNh/ISD) + upper air (IGRA) stations
3. **Download** — Fetch data from NCEI (GHCNh auto-converted to ISD)
4. **Land Use** — Run AERSURFACE (US: NLCD GeoTIFF) or enter manual params (non-US)
5. **Run AERMET** — Execute all 3 stages per year
6. **Results** — Completeness table + downloadable .SFC/.PFL files

**Dependencies:** flask, requests, certifi (that's it)
**Launch:** `python server.py` or double-click `launch.bat` on Windows
**EPA executables required:** aermet.exe, aersurface.exe (optional), aerminute.exe (optional) in `bin/`

### 2. Rust Rewrite (`aermet-tool/` — in progress)

Same functionality as the Python version, compiled to a single binary.
**Same API contract** — the frontend works unchanged with either backend.
Uses axum (HTTP), tokio (async), reqwest (HTTP client), rust-embed (static files).
Release profile: `opt-level = "z"`, LTO, stripped — targeting ~10-15MB binary.
EPA executables are embedded in the binary and extracted to `~/.aermet-tool/bin/` on first run.

---

## Critical Domain Knowledge

### Data Sources
| Source | Format | Used For | Downloaded From |
|--------|--------|----------|-----------------|
| GHCNh | Pipe-separated values (PSV) | Surface observations | NCEI |
| ISD | Fixed-width (variable length) | AERMET surface input | Converted from GHCNh |
| IGRA | Fixed-width text | Upper air soundings | NCEI (AERMET reads natively) |
| TD-3505 | ASOS 1-minute data | AERMINUTE input | NCEI |
| NLCD | GeoTIFF | Land use (AERSURFACE) | User-provided |
| FSL | Fixed-width text | Upper air (alternative) | Converted from IGRA or Wyoming |

### GHCNh -> ISD Conversion (the core algorithm)

This is the most complex and important code in the repo. Key rules:

1. **Cloud cover: GA only** — Only output GA (Sky Cover Layer) records. Do NOT generate GD/GE/GF records. GHCNh only has raw observations, not derived layers.

2. **SYNOP sky cover fill** — FM-12 SYNOP reports often have blank sky cover. The converter looks back up to 45 minutes for valid sky cover data from the same station. This prevents missing-value problems downstream.

3. **Empty sky cover = clear** — If all `sky_cover_1/2/3` are empty (not explicitly "CLR"), output `GA1005+999999999` (0/8ths clear, quality=5, missing height).

4. **Negative Fahrenheit** — Temps below 0F use "X" prefix: -4F -> `X04`. Clamped to -99F (`X99`). Zero is space-padded (`  0`).

5. **Calm wind direction** — When wind speed is 0 or code includes "C-Calm", direction is `00` (not 360 or missing).

6. **Unit conversions:**
   - Temperature: C -> F (with rounding rules)
   - Wind speed: m/s -> knots
   - Pressure: Pa -> hPa (divide by 100)
   - Cloud base height: meters (no conversion needed for GA)
   - Cloud cover: oktas (0-8 scale)

7. **Hourly assignment** — Observations are assigned to local hours. Prefers METAR over SYNOP when both exist for same hour.

8. **RH calculation** — If relative humidity field is empty, calculate from dewpoint temperature using Magnus formula.

### IGRA Handling
- Downloads full-history files from NCEI (can be very large)
- Parses text headers (`#StationID Year Mo Dy Hr ...`) to find year boundaries
- Extracts only needed years (avoids parsing entire file)
- AERMET reads IGRA format natively (no conversion needed)

### Completeness Assessment
- Evaluated from **final .SFC output**, not raw inputs
- An hour is valid if sensible heat flux is not a missing-value code
- **Calm wind hours (zero speed) ARE valid** — do not count as missing
- Checked on quarterly or annual basis per user specification
- AERMET runs per-year even for multi-year requests (for quality checking)

### Station Discovery
- Downloads & caches station inventories from NCEI
- Filters by distance from project location and date range overlap
- Ranks by proximity and historical completeness
- User can refine station coordinates on satellite map (critical for AERSURFACE accuracy)

---

## Standalone CLI Tools (Root Directory)

These are independent utilities, not part of the AERMET automation wizard:

- **`igra_to_fsl.py`** — Converts IGRA v2 fixed-width format to FSL text format. Supports date range filtering, station metadata overrides. FSL line types: 254, 1, 2, 3, 4, 5, 6, 7, 9.

- **`igra_fsl_tool.py`** — Automated download + conversion: looks up IGRA station from 3-letter call sign (e.g., "DTX"), downloads full history, converts to FSL with per-year and combined output files.

- **`uwyo_to_fsl.py`** — Downloads 12Z soundings from University of Wyoming archive and converts to FSL. Rate-limited (3s between requests to be polite).

---

## Important Gotchas & Quirks

1. **No unit tests exist.** All modules are testable but there are zero tests. If adding tests, GHCNh parsing edge cases, unit conversions, and IGRA trimming are highest priority.

2. **Three parallel implementations of GHCNh->ISD exist:** JavaScript (`app/ghcnh-to-isd.js`), Python (`aermet/core/ghcnh_to_isd.py`), and Rust (`aermet-tool/src/ghcnh_to_isd.rs`). Changes to conversion logic must be synchronized across all three (or at minimum Python and Rust).

3. **SSL/TLS fallback chain** — HTTP client tries certifi -> system default -> unverified (with warning). Handles machines with outdated CA bundles.

4. **Project workspaces use UUID-based directories** — Each run gets a unique 8-char hex ID. All intermediate files are preserved for debugging.

5. **EPA utilities are Windows-only .exe files** — Users must provide them. The Rust version embeds them in the binary.

6. **CD144 time zone: NO daylight saving time** — Uses fixed UTC offset provided by user. No automatic DST. If offset moves a record across a year boundary, separate output files are generated.

7. **GHCNh station list is fixed-width** — Specific column positions. Must strip leading zeros correctly.

8. **Large file handling** — GHCNh downloads can be 100+ MB. Uses streaming (`iter_content(chunk_size=65536)`) with progress callbacks.

9. **The `app/` directory is deployed to GitHub Pages** via `.github/workflows/pages.yml`. It's the original client-side converter, now somewhat superseded by the AERMET automation tool but still useful as a standalone converter.

10. **Windows batch files** handle Python-not-on-PATH gracefully with `where python` checks.

---

## Development Patterns

### Python (aermet/)
- Flask REST API with JSON responses
- Thread-safe in-memory progress tracking for long operations
- Each core module is standalone and importable
- `server.py` is the only entry point — imports everything from `core/`
- No ORM, no database — project state is flat JSON files

### Rust (aermet-tool/)
- axum routes mirror Flask routes exactly (same URLs, same JSON shapes)
- Static files embedded at compile time via `rust-embed`
- Async throughout (tokio runtime)
- Each `.rs` module maps 1:1 to a Python `core/*.py` module

### Frontend
- Vanilla HTML/JS/CSS (no framework, no build step)
- Same frontend served by both Python and Rust backends
- Wizard-style multi-step UI with progress indicators

---

## Git & CI
- **Default branch:** main (remote), master (local tracking may differ)
- **CI:** GitHub Pages deployment only (`.github/workflows/pages.yml`)
- **No automated tests in CI** (no tests exist)
- **.gitignore:** `*.fsl`, `*.log`, `__pycache__/`, `*.pyc`, `gui/output/`

---

## Key Documentation Files

Read these for deep dives:
- **`docs/Conversion Notes.md`** — THE authoritative reference for all format conversions. Read this before touching any converter code.
- **`docs/aermet-automation-plan.md`** — Complete design spec with all 20+ API endpoints, workflow steps, and architecture decisions.
- **`docs/rust-rewrite-plan.md`** — Rust port strategy, binary size targets, 9-day implementation plan.
- **`aermet/README.md`** — User-facing quick start guide.

---

## Common Tasks

### Adding a new format conversion
1. Read `docs/Conversion Notes.md` for format specs
2. Implement in Python (`aermet/core/`) first
3. Port to Rust (`aermet-tool/src/`) with identical behavior
4. If client-side needed, add JS version in `app/`
5. Add sample data in `samples/`

### Modifying GHCNh -> ISD conversion
1. **Read `docs/Conversion Notes.md` first** — it documents every edge case
2. Update Python (`aermet/core/ghcnh_to_isd.py`)
3. Update Rust (`aermet-tool/src/ghcnh_to_isd.rs`)
4. Update JS (`app/ghcnh-to-isd.js`) if the client-side tool is still maintained
5. Test with sample files in `samples/`

### Adding an API endpoint
1. Add route in `aermet/server.py`
2. Add corresponding handler in `aermet-tool/src/server.rs`
3. Update frontend in `aermet/static/` and `aermet-tool/static/`
4. Document in `docs/aermet-automation-plan.md`
