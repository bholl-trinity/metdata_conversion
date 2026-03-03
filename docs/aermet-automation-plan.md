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
| **Backend** | Python (Flask) | Local Windows server; handles file I/O, subprocess execution, data downloads |
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

### Step 3: Data Acquisition

Download data for candidate stations and requested years:

| Data Type | Source | Download Format | AERMET Input | Notes |
|-----------|--------|----------------|--------------|-------|
| Hourly surface | NCEI | GHCNh (.psv) | ISD (.ish) | Downloaded as GHCNh, then converted to ISD using existing converter logic. When EPA adds native GHCNh support to AERMET, the conversion step is removed. |
| Upper air | IGRA (Integrated Global Radiosonde Archive) | IGRA format | FSL | Downloaded from NCEI IGRA archive; converted to FSL format for AERMET |
| 1-minute ASOS | NCEI | TD-3505 | TD-3505 | Only available for US ASOS stations; processed by AERMINUTE |
| NLCD land use | MRLC/USGS | GeoTIFF | GeoTIFF | Only for US sites; used by AERSURFACE. Need strategy for downloading appropriate tiles based on project location. |

**GHCNh → ISD conversion pipeline:**
The existing `ghcnh-to-isd.js` converter logic will be ported to Python (or
wrapped) so it can run server-side. This gives us a clean path: download GHCNh
from NCEI → convert to ISD → feed to AERMET. This is a temporary bridge until
EPA updates AERMET to read GHCNh directly.

**IGRA upper air pipeline:**
Upper air data will be downloaded from the IGRA archive at NCEI and converted
to FSL format for AERMET. The existing `uwyo_to_fsl.py` provides a reference
for FSL output formatting, but the download source and input parsing will
target the IGRA format instead of Wyoming CSV.

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

**For each candidate surface station × year:**
1. Generate AERMET Stage 1 control file (EXTRACT pathway)
2. Execute AERMET.exe Stage 1
3. Parse the AERMET message file for data recovery statistics
4. Calculate completeness:
   - **Quarterly**: Each calendar quarter must meet threshold independently
   - **Annual**: Full year must meet threshold
5. Flag pass/fail for each station-year combination

**Present results to user:**
- Table: Station × Year matrix with completeness percentages
- Color-coded: green (pass), yellow (marginal), red (fail)
- User selects final station-year combinations to proceed with

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

**Provide to user:**
- .SFC file (surface meteorological data for AERMOD)
- .PFL file (profile/upper air data for AERMOD)
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
- **Interactive station map** (optional — could use Leaflet.js with OSM tiles)
- **Real-time log panel** showing backend progress (WebSocket or SSE)
- **Completeness results table** with color-coded pass/fail
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
   DATA      {upper_air_file}  FSL
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
  Radiosonde Archive
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

### Still Open
1. **Multi-year handling**: Run AERMET per-year or multi-year in a single run?
   Per-year is simpler for quality checking but requires more control files.
2. **Onsite data**: Should we support onsite meteorological data as an optional
   input? (AERMET supports it but it adds significant complexity)
3. **GHCNh→ISD converter porting**: Port the JavaScript converter to Python
   for server-side use, or use a JS runtime (Node.js) as a subprocess?
   Python port is cleaner but requires re-implementation effort.
4. **IGRA format parsing**: Need to investigate the exact IGRA download format
   and write a parser/converter to FSL format. The existing `uwyo_to_fsl.py`
   handles FSL output but parses Wyoming CSV input — the IGRA input format
   is different.
5. **User distribution**: How will end users install/run this tool? Options:
   - Python + pip install with a launch script
   - Bundled executable via PyInstaller
   - Docker container (adds complexity for Windows users)
   - Simple ZIP with batch file launcher
