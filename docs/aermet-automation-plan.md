# AERMET Automation Tool — Design Plan

## 1. Overview

A locally-run Windows application with a web browser frontend that automates
the entire US EPA AERMET meteorological preprocessing workflow. The user
provides a project location and data quality requirements; the tool discovers
weather stations, downloads data from NCEI and other sources, evaluates data
completeness via dummy AERMET runs, runs the EPA utilities (AERMET, AERSURFACE,
AERMINUTE), and delivers production-ready AERMOD meteorological input files
(.SFC and .PFL).

**Key constraint:** All computation and file processing runs locally on the
user's Windows PC. Internet access is used only for downloading meteorological
data and geocoding lookups.

---

## 2. Architecture

### Why this differs from the existing converter
The existing met-data conversion app is a static client-side SPA deployed to
GitHub Pages. This project is fundamentally different in scope and requires:
- A local Python backend running on the user's Windows PC
- Execution of Windows .exe files (AERMET, AERSURFACE, AERMINUTE)
- Local filesystem management for control files, input data, and outputs
- Internet access for data downloads from NCEI, Wyoming, etc.
- Geocoding lookups (address/airport code → lat/lon)

The existing GHCNh→ISD converter code will be reused as an intermediate
processing step. Currently AERMET does not support the GHCNh format directly,
so surface data downloaded as GHCNh will be converted to ISD/ISH format using
our existing converter before being fed to AERMET. When EPA updates AERMET to
support GHCNh natively, this conversion step can be removed.

### Proposed stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Frontend** | HTML / CSS / vanilla JS | Browser-based UI; served locally by the Python backend |
| **Backend** | Python (Flask) | Local Windows server; handles file I/O, subprocess execution, data downloads. Distributed as unzip-and-run (PyInstaller bundle or embedded Python). |
| **EPA Utilities** | AERMET.exe, AERSURFACE.exe, AERMINUTE.exe | Executed locally via `subprocess` |
| **Data Downloads** | Python `requests` | Surface (GHCNh from NCEI → converted to ISD), upper air (Wyoming), 1-min ASOS |
| **Format Conversion** | Existing ghcnh-to-isd.js (ported to Python or called via Node) | GHCNh → ISD conversion; temporary until EPA adds native GHCNh support |
| **Geocoding** | Nominatim (OpenStreetMap) or US Census geocoder | Address → lat/lon; no API key required |
| **Airport Lookup** | Bundled airport database (CSV/JSON) | ICAO code → lat/lon; ~10K records, static file |

### Directory structure (proposed)

```
metdata_conversion/
├── app/                        # Existing converter (unchanged)
│   ├── index.html
│   ├── converter.js
│   ├── ghcnh-to-isd.js
│   └── ghcnh-to-cd144.js
├── aermet/                     # NEW — AERMET automation tool
│   ├── server.py               # Flask/FastAPI backend entry point
│   ├── static/                 # Frontend assets
│   │   ├── index.html          # Main UI
│   │   ├── app.js              # Frontend controller
│   │   └── style.css           # Styles
│   ├── core/                   # Backend logic modules
│   │   ├── __init__.py
│   │   ├── geocode.py          # Address/airport → lat/lon
│   │   ├── stations.py         # Station discovery & ranking
│   │   ├── download.py         # Data acquisition (surface, upper air, 1-min)
│   │   ├── completeness.py     # Data completeness evaluation
│   │   ├── aermet_runner.py    # AERMET control file generation & execution
│   │   ├── aersurface.py       # AERSURFACE control file generation & execution
│   │   ├── aerminute.py        # AERMINUTE control file generation & execution
│   │   └── project.py          # Project state management
│   ├── data/                   # Static reference data
│   │   ├── airports.csv        # ICAO airport database
│   │   ├── isd_station_list.csv # NCEI ISD station inventory
│   │   └── upper_air_stations.csv # Upper air station inventory
│   ├── templates/              # AERMET/AERSURFACE/AERMINUTE control file templates
│   │   ├── aermet_s1.tpl
│   │   ├── aermet_s2.tpl
│   │   ├── aermet_s3.tpl
│   │   ├── aersurface.tpl
│   │   └── aerminute.tpl
│   ├── bin/                    # EPA executables (bundled with repo)
│   │   ├── aermet.exe
│   │   ├── aersurface.exe
│   │   └── aerminute.exe
│   └── projects/               # Working directory for project runs
│       └── .gitkeep
├── docs/
├── samples/
└── uwyo_to_fsl.py
```

---

## 3. Workflow — Step by Step

### Step 1: User Input & Location Setup

**User provides:**
- **Location** (one of three methods):
  - Street address → geocoded to lat/lon via Nominatim or Census API
  - Direct latitude/longitude entry
  - 4-letter ICAO airport code (e.g., KLAX, EGLL) → looked up from bundled DB
- **Data period**:
  - Number of years of data needed (e.g., 5)
  - Preferred start year (e.g., 2019)
- **Completeness requirements**:
  - Threshold percentage (default: **90%**)
  - Evaluation basis: **Quarterly** (default) or Annual (radio button)
- **Site country** (auto-detected from coordinates or user-confirmed):
  - US sites: AERSURFACE + AERMINUTE available
  - Non-US sites: User provides land use data manually

**Backend actions:**
- Geocode/resolve location to lat/lon
- Determine if site is in the US (reverse geocode or simple bounding box)
- Create a project workspace directory

### Step 2: Station Discovery

**Surface stations:**
- Load NCEI ISD station inventory (updated periodically)
- Filter by distance from project location (configurable radius, e.g., 100 km)
- Filter by date range overlap with requested period
- Rank by: distance, data availability, station type (ASOS preferred)
- Present top candidates to user with metadata (name, ID, distance, years active)

**Upper air stations:**
- Load IGRA station inventory from NCEI
- Filter by distance (larger radius — upper air stations are sparser, ~300 km)
- Rank by distance and data availability
- Present candidates to user

**User action:** Select preferred surface and upper air stations (or accept defaults)

**Station coordinate refinement (surface station):**
AERSURFACE requires high-precision station coordinates. The official coordinates
in station inventories are often not accurate enough. After the user selects
their preferred surface station:
1. The official station coordinates are displayed on an interactive satellite
   imagery map (Google Maps or similar) embedded in the UI.
2. A draggable marker is placed at the official coordinates.
3. The user visually locates the actual station (e.g., the anemometer mast or
   instrument cluster on the airfield) and drags the marker to that position.
4. The user clicks an **"Update Station Coordinates"** button.
5. The refined lat/lon replaces the official coordinates for all downstream
   processing — specifically AERSURFACE (center point) and the AERMET
   `SURFACE LOCATION` control file entry.

This is critical for correct AERSURFACE land use classification, since even
small coordinate errors can shift the analysis into the wrong land use category.

### Step 3: Data Acquisition

Download data for candidate stations and requested years:

| Data Type | Source | Download Format | AERMET Input | Notes |
|-----------|--------|----------------|--------------|-------|
| Hourly surface | NCEI | GHCNh (.psv) | ISD (.ish) | Downloaded as GHCNh, then converted to ISD using existing converter logic. When EPA adds native GHCNh support to AERMET, the conversion step is removed. |
| Upper air | IGRA (Integrated Global Radiosonde Archive) | IGRA format | IGRA (native) | Downloaded from NCEI IGRA archive; AERMET reads IGRA directly. Full-history file is trimmed to years of interest before use. |
| 1-minute ASOS | NCEI | TD-3505 | TD-3505 | Only available for US ASOS stations; processed by AERMINUTE |
| NLCD land use | MRLC/USGS | GeoTIFF | GeoTIFF | Only for US sites; used by AERSURFACE. Need strategy for downloading appropriate tiles based on project location. |

**GHCNh → ISD conversion pipeline:**
The existing `ghcnh-to-isd.js` converter logic will be ported to Python (or
wrapped) so it can run server-side. This gives us a clean path: download GHCNh
from NCEI → convert to ISD → feed to AERMET. This is a temporary bridge until
EPA updates AERMET to read GHCNh directly.

**IGRA upper air pipeline:**
AERMET reads IGRA format natively — no conversion needed. The NOAA IGRA
archive provides full-history files (entire station record, potentially
decades). The tool will:
1. Download the full-history IGRA data file for the selected station from NCEI.
2. Parse the text-based IGRA format (which has clearly readable date headers)
   to identify the boundaries of the years of interest.
3. Extract/trim only the needed years into a smaller file.
4. Feed the trimmed IGRA file directly to AERMET.

This keeps file sizes manageable and AERMET runs fast.

**NLCD download strategy:**
NLCD GeoTIFF files are very large (full CONUS is multiple GB). Approach:
1. **Preferred: API automation** — Investigate MRLC web services, USGS TNM
   API, or similar for programmatic download of a clipped geographic area
   around the project site (AERSURFACE typically needs ~1 km radius around
   the surface station).
2. **Fallback: Guided manual download** — If no suitable API exists, generate
   a URL with pre-loaded coordinate boundaries for nationalmap.gov or the
   MRLC clearinghouse website so the user can quickly download the right
   file themselves. Provide clear instructions in the UI.
3. **Direct upload** — User can always provide their own NLCD GeoTIFF file
   directly if they already have it.

**Progress reporting:** Show download status in UI for each data file

### Step 4: Data Quality Assessment (Dummy AERMET Runs)

This is the key differentiator — running AERMET Stage 1 to evaluate whether
candidate station/year combinations meet the user's completeness criteria.

**Completeness is assessed from the final SFC output file**, not from raw
inputs or intermediate AERMET messages. A given hour's validity depends on
the combination of surface and upper air values — the same observation may
be valid for one time of day but missing at another. Therefore:

**For each candidate surface station × year:**
1. Run the full AERMET pipeline (Stages 1–3) to produce a preliminary SFC file
2. Parse the SFC output file to calculate hourly completeness:
   - An hour is **valid** if it contains real (non-missing) values for key
     parameters (e.g., surface heat flux is a real value, not a missing code)
   - An hour with **calm winds** (zero wind speed) is **not** counted as missing
   - Missing-value sentinel codes in the SFC format indicate invalid hours
3. Calculate completeness percentage = valid hours / total hours
4. Evaluate against user threshold:
   - **Quarterly**: Each calendar quarter must meet threshold independently
   - **Annual**: Full year must meet threshold
5. Flag pass/fail for each station-year combination

**Present results to user:**
- Table: Station × Year matrix with completeness percentages
- Color-coded: green (pass), yellow (marginal), red (fail)
- User selects final station-year combinations to proceed with

**If completeness falls short:** Display a message to the user identifying
which specific years or quarters fell below the completeness threshold and
by how much. (Future enhancement: automatically check adjacent years for
better-quality substitutes.)

**Fallback logic:**
- If preferred start year doesn't meet criteria, suggest alternative years
- If no single station meets criteria, suggest combining stations (if AERMET allows)

### Step 5: AERSURFACE — Land Use Processing

**If site is in the US:**
1. Determine NLCD data tile(s) needed based on project location
2. Download NLCD GeoTIFF if not already cached
3. Generate AERSURFACE control file:
   - Center coordinates (project lat/lon or surface station)
   - Temporal resolution (monthly or seasonal)
   - Sector configuration (default 12 × 30° sectors)
   - Airport flag (if surface station is at an airport)
4. Execute AERSURFACE.exe
5. Parse output for surface characteristics:
   - Albedo by sector and season/month
   - Bowen ratio by sector and season/month
   - Surface roughness length by sector and season/month

**If site is NOT in the US:**
1. Present user with a form to manually enter surface characteristics
2. Required: albedo, Bowen ratio, surface roughness
3. Options: by sector and by season/month, or single values
4. Provide reference tables / guidance values for common land use types

### Step 6: AERMINUTE — 1-Minute Wind Processing

**Applicability check:**
- Only for US ASOS stations
- Check if 1-minute data files exist for the station and period
- Check the AERMINUTE station compatibility list

**If applicable:**
1. Download 1-minute ASOS wind data from NCEI (TD-3505 format)
2. Generate AERMINUTE control file
3. Execute AERMINUTE.exe for each year
4. Output: supplemental wind data file for AERMET Stage 2

**If not applicable:**
- Skip this step (inform user)
- AERMET will process without 1-minute data substitution

### Step 7: Final AERMET Run (3 Stages)

**Stage 1 — Extract & QA:**
- Generate control file with EXTRACT and QA pathways
- Input: ISD surface data, FSL upper air data
- Execute AERMET.exe
- Check message file for errors/warnings
- Output: QA'd extracted data files

**Stage 2 — Merge:**
- Generate control file with MERGE pathway
- Input: Stage 1 output files + AERMINUTE output (if available)
- Execute AERMET.exe
- Check message file
- Output: merged meteorological data file

**Stage 3 — Calculate boundary layer parameters:**
- Generate control file with METPREP pathway
- Input: Stage 2 merged file + AERSURFACE output (or manual surface chars)
- Station and project location coordinates
- Execute AERMET.exe
- Check message file
- Output: **AERMOD-ready .SFC and .PFL files**

### Step 8: Output & Delivery

**Multi-year output options** (user selects before final run):
- **Combined**: One .SFC and one .PFL file covering all processed years
- **Individual**: Separate .SFC/.PFL file pairs for each year
- **Both**: Both combined and per-year files

**Provide to user:**
- .SFC file(s) (surface meteorological data for AERMOD)
- .PFL file(s) (profile/upper air data for AERMOD)
- Summary report:
  - Stations used (surface, upper air)
  - Period covered
  - Data completeness statistics
  - AERSURFACE parameters used
  - AERMINUTE status
  - Any warnings or substitutions
- Option to download all files as a ZIP archive
- Option to download intermediate files (AERMET message files, etc.)

---

## 4. Frontend Design

### Page Layout (Multi-Step Wizard)

The UI should guide the user through the workflow as a step-by-step wizard
with a progress indicator showing which stage they're in.

```
┌─────────────────────────────────────────────────────────┐
│  AERMET Automation Tool                    [step 1 of 7]│
│  ═══════════════════════════════════════════════════════ │
│  ● Location  ○ Stations  ○ Data  ○ Quality  ○ Land Use │
│    ○ AERMINUTE  ○ Results                               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Project Location                                       │
│  ┌───────────────────────────────────────┐              │
│  │ ○ Street Address                      │              │
│  │   [____________________________________]             │
│  │ ○ Latitude / Longitude                │              │
│  │   Lat: [________]  Lon: [________]    │              │
│  │ ○ Airport Code (ICAO)                 │              │
│  │   [____]                              │              │
│  └───────────────────────────────────────┘              │
│                                                         │
│  Data Requirements                                      │
│  ┌───────────────────────────────────────┐              │
│  │ Years of data needed:  [5___]         │              │
│  │ Preferred start year:  [2019]         │              │
│  │ Completeness threshold: [90]%         │              │
│  │ Evaluate: ● Quarterly  ○ Annual       │              │
│  └───────────────────────────────────────┘              │
│                                                         │
│                              [Next →]                   │
└─────────────────────────────────────────────────────────┘
```

### Key UI Features
- **Progress stepper** at top showing workflow stages
- **Interactive station map** (Leaflet.js with OSM tiles or Google Maps for satellite imagery)
- **Station coordinate refinement map**: After surface station selection, an
  embedded satellite map with a draggable marker for visually pinpointing the
  actual station location. Official coordinates auto-populate; user drags
  marker to the real position and clicks "Update Station Coordinates." The
  refined coordinates are used for AERSURFACE and AERMET SURFACE LOCATION.
- **Real-time log panel** showing backend progress (WebSocket or SSE)
- **Completeness results table** with color-coded pass/fail
- **Multi-year output options**: Radio buttons for combined files, per-year
  files, or both
- **Download panel** for final output files
- **Consistent styling** with existing converter app (blues, greens, clean layout)

---

## 5. Backend API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/geocode` | Convert address or airport code to lat/lon |
| POST | `/api/project/create` | Create new project workspace |
| GET | `/api/stations/surface` | Find nearby surface stations |
| GET | `/api/stations/upperair` | Find nearby upper air stations |
| POST | `/api/download/surface` | Download surface data for station/years |
| POST | `/api/download/upperair` | Download upper air data |
| POST | `/api/download/oneminute` | Download 1-minute ASOS data |
| POST | `/api/aermet/stage1` | Run AERMET Stage 1 (quality check) |
| GET | `/api/completeness` | Get completeness results |
| POST | `/api/aersurface/run` | Run AERSURFACE |
| POST | `/api/aersurface/manual` | Submit manual land use data |
| POST | `/api/aerminute/run` | Run AERMINUTE |
| POST | `/api/aermet/run` | Run full AERMET (Stages 1-3) |
| GET | `/api/project/status` | Get current project/run status |
| GET | `/api/project/download` | Download output files (ZIP) |
| WS | `/ws/progress` | WebSocket for real-time progress updates |

---

## 6. EPA Utility Control File Templates

### AERMET Stage 1 (extract + QA) — key keywords
```
JOB
   MESSAGES  aermet_s1.msg
   REPORT    aermet_s1.rpt

UPPERAIR
   DATA      {upper_air_file}  IGRA
   EXTRACT   {ua_extract_file}
   AUDIT     UATT UAWS UALR
   QAOUT     {ua_qa_file}
   XDATES    {start_date}  TO  {end_date}
   LOCATION  {ua_station_id}  {ua_lat}  {ua_lon}

SURFACE
   DATA      {surface_file}  {surface_format}
   EXTRACT   {sf_extract_file}
   AUDIT     SLVP PRES CLHT TSKC PWTH APTS
   QAOUT     {sf_qa_file}
   XDATES    {start_date}  TO  {end_date}
   LOCATION  {sf_station_id}  {sf_lat}  {sf_lon}
   {oneminute_keyword}
```

### AERMET Stage 2 (merge)
```
JOB
   MESSAGES  aermet_s2.msg
   REPORT    aermet_s2.rpt

UPPERAIR
   QAOUT     {ua_qa_file}

SURFACE
   QAOUT     {sf_qa_file}
   {oneminute_keyword}

MERGE
   OUTPUT    {merge_file}
   XDATES    {start_date}  TO  {end_date}
```

### AERMET Stage 3 (METPREP)
```
JOB
   MESSAGES  aermet_s3.msg
   REPORT    aermet_s3.rpt

METPREP
   DATA      {merge_file}
   XDATES    {start_date}  TO  {end_date}
   OUTPUT    {sfc_file}
   PROFILE   {pfl_file}
   {anemometer_height}
   FREQ_SECT ANNUAL  {num_sectors}
   {sector_definitions}
   {surface_characteristics}
   SITE_CHAR
   NWS_HGT   {anemometer_height_value}
   AERSURF    {aersurface_output_file}
   METHOD     REFLEVEL  SUBNWS
```

---

## 7. Key Technical Considerations

### Data sources & availability
- **Surface (GHCNh)**: Available globally from NCEI; converted to ISD locally
- **Upper air (IGRA)**: Global coverage via NCEI's Integrated Global
  Radiosonde Archive; AERMET reads IGRA natively (no format conversion);
  full-history files trimmed to years of interest
- **1-minute ASOS (TD-3505)**: US only; not available for all stations or
  all years; processed by AERMINUTE
- **NLCD**: US only (CONUS); updated roughly every 3 years; needed for
  AERSURFACE

### Windows .exe execution
- Backend runs natively on Windows
- Use `subprocess.run()` with timeout and error capture
- Capture stdout/stderr for debugging
- Parse message (.msg) files for structured error reporting

### File management
- Each project gets a unique workspace directory
- Intermediate files preserved for debugging/review
- Final outputs clearly separated
- Cleanup option after download

### Error handling & resilience
- Data download failures: retry with backoff, try alternate sources
- AERMET execution failures: parse message file, present errors to user
- Network timeouts: queue and retry
- Invalid user input: validate on frontend and backend

### Performance considerations
- Downloading multiple years of data can take minutes
- AERMET runs are generally fast (seconds per year)
- AERSURFACE can be slow if processing large NLCD tiles
- Use async/background tasks with progress reporting

---

## 8. Implementation Phases

### Phase 1: Foundation (Backend + Basic Frontend)
- [ ] Set up Flask/FastAPI project structure
- [ ] Implement geocoding (address, airport code, direct lat/lon)
- [ ] Build airport ICAO database
- [ ] Create project workspace management
- [ ] Build basic wizard UI (Step 1: location input)
- [ ] Set up WebSocket or SSE for progress reporting

### Phase 2: Station Discovery
- [ ] Import and index NCEI ISD station inventory
- [ ] Import upper air station inventory
- [ ] Implement distance-based station search
- [ ] Build station selection UI (Step 2)
- [ ] Optional: integrate map view

### Phase 3: Data Acquisition
- [ ] Surface data download from NCEI
- [ ] Upper air data download (extend uwyo_to_fsl.py)
- [ ] 1-minute ASOS data download and availability check
- [ ] Download progress UI (Step 3)

### Phase 4: Quality Assessment
- [ ] AERMET Stage 1 control file generation
- [ ] AERMET execution wrapper
- [ ] Message file parser for completeness stats
- [ ] Quarterly and annual completeness calculation
- [ ] Quality results UI with pass/fail matrix (Step 4)

### Phase 5: Land Use & AERMINUTE
- [ ] AERSURFACE control file generation and execution
- [ ] NLCD data acquisition
- [ ] Manual land use input form for non-US sites
- [ ] AERMINUTE control file generation and execution
- [ ] Land use UI (Step 5) and AERMINUTE UI (Step 6)

### Phase 6: Final AERMET Run & Output
- [ ] Full 3-stage AERMET control file generation
- [ ] Stage execution with progress reporting
- [ ] Output file packaging (ZIP)
- [ ] Summary report generation
- [ ] Results/download UI (Step 7)

### Phase 7: Polish & Testing
- [ ] End-to-end testing with real data
- [ ] Error handling and edge cases
- [ ] UI polish and responsive design
- [ ] Documentation

---

## 9. Open Questions

### Resolved
- ~~Deployment~~: **Local Windows PC** with browser frontend. Confirmed.
- ~~Data source for surface~~: **GHCNh from NCEI**, converted to ISD via existing converter. Confirmed.
- ~~Data source for upper air~~: **IGRA**. Confirmed.
- ~~1-minute data format~~: **TD-3505**. Confirmed.
- ~~Existing converter integration~~: **Yes** — GHCNh→ISD converter will be used as intermediate step until EPA updates AERMET. Confirmed.
- ~~EPA executable distribution~~: **Bundle in repo.** AERMET.exe, AERSURFACE.exe, and AERMINUTE.exe will be included in the repository/package so they ship with the tool. No separate install needed.
- ~~NLCD download strategy~~: **API-first, with guided manual fallback.** We will investigate whether MRLC/USGS/TNM has an API to programmatically download a clipped area. If an API is available, automate it. If not, guide the user through the manual download process — e.g., generate a URL with pre-loaded coordinate boundaries for the relevant website (nationalmap.gov or MRLC clearinghouse) so the user can quickly grab the right file. No AI-driven browser automation (no Claude/Cowork dependency). User can also provide their own NLCD file directly.
- ~~GHCNh→ISD converter porting~~: **Best technical approach, implementer's discretion.** Reuse the existing converter logic in whatever way is most practical for the Python backend (likely a Python port of the core JS logic).
- ~~Onsite data~~: **Deferred to future release.** Not in v1.
- ~~User distribution~~: **Zero-install, unzip-and-run.** The tool should be distributable as a ZIP that the user extracts and launches — no formal installation, no pip install, no Docker. A batch file launcher starts the Python backend and opens the browser. This means either bundling a Python runtime (via PyInstaller or embedded Python) or requiring Python as the sole prerequisite.
- ~~Multi-year handling~~: **Per-year processing with flexible output options.** AERMET runs per-year for quality checking. User then chooses output format: (a) combined — one SFC and one PFL file covering all years, (b) individual — separate SFC/PFL files per year, or (c) both. The UI presents this as a simple radio/checkbox choice before the final run.
- ~~IGRA format~~: **AERMET reads IGRA natively — no conversion needed.** Download full-history IGRA file from NOAA, trim to years of interest (parse text date headers), feed directly to AERMET. No FSL conversion required.
- ~~Station coordinate precision~~: **Interactive satellite map for refinement.** After surface station selection, official coordinates populate on a satellite map with a draggable marker. User visually locates the actual station and drags the marker to it, then clicks "Update Station Coordinates." Refined lat/lon is used for AERSURFACE and AERMET SURFACE LOCATION.

### Still Open
*No remaining open questions — all major design decisions are resolved.*

### Deferred to Future Release
- **Onsite data**: AERMET supports onsite meteorological data as an optional
  input, but this adds significant complexity. Will not be in the initial
  release; can be added later.
