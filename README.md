# AERMET Automation Tool

A locally-run Windows application that automates the entire EPA AERMET
meteorological preprocessing workflow. Enter a project location and data
quality requirements; the tool discovers weather stations, downloads data,
runs the EPA utilities, and delivers production-ready AERMOD meteorological
input files (.SFC and .PFL).

## Quick Start (Windows)

1. **Download** this repository as a ZIP and extract it
2. **Place EPA executables** in the `bin/` folder:
   - `aermet.exe`
   - `aersurface.exe` (optional — US sites only)
   - `aerminute.exe` (optional — US ASOS stations only)
3. **Double-click `launch.bat`**
   - This installs Python dependencies and starts the server
   - Your browser opens automatically to `http://localhost:5000`
4. **Follow the 6-step wizard** in your browser

### Prerequisites

- **Python 3.8+** installed and on your PATH
  ([download here](https://www.python.org/downloads/))
- **EPA executables** — download from the
  [EPA SCRAM website](https://www.epa.gov/scram/air-quality-dispersion-modeling-related-model-support-programs)

## What It Does

The wizard walks you through:

| Step | What happens |
|------|-------------|
| **1. Location** | Enter an address, lat/lon, or airport code. Set years needed and completeness threshold. |
| **2. Stations** | Tool finds nearby surface (ISD) and upper air (IGRA) stations. You pick the ones to use and refine station coordinates on a satellite map. |
| **3. Download** | Surface data (GHCNh → auto-converted to ISD), upper air (IGRA, trimmed to your years), and 1-minute ASOS data are downloaded from NCEI. |
| **4. Land Use** | Run AERSURFACE with an NLCD file (US sites) or enter surface characteristics manually (non-US sites). |
| **5. Run AERMET** | All 3 AERMET stages run for each year. Output option: combined multi-year files, individual per-year, or both. |
| **6. Results** | Color-coded completeness table (from the final .SFC file — calm winds are valid, not missing). Download .SFC/.PFL files individually or as a ZIP. |

## Data Sources

- **Surface**: GHCNh (NCEI) — converted to ISD format automatically
- **Upper Air**: IGRA (NCEI) — AERMET reads IGRA natively; full-history files
  are trimmed to your years of interest
- **1-Minute ASOS**: NCEI TD-3505 — processed by AERMINUTE (US ASOS stations only)
- **Land Use**: NLCD GeoTIFF — user-provided for AERSURFACE (US sites)

## Project Structure

```
aermet-automation/
├── server.py              # Flask backend (start here)
├── launch.bat             # Windows launcher
├── requirements.txt       # Python dependencies
├── core/                  # Backend modules
│   ├── geocode.py         # Location resolution
│   ├── stations.py        # Station discovery
│   ├── download.py        # Data acquisition
│   ├── ghcnh_to_isd.py    # GHCNh → ISD format converter
│   ├── igra.py            # IGRA download & year trimming
│   ├── aermet_runner.py   # AERMET control files & execution
│   ├── completeness.py    # SFC file completeness assessment
│   ├── aersurface.py      # AERSURFACE control files & execution
│   ├── aerminute.py       # AERMINUTE control files & execution
│   └── project.py         # Project state management
├── static/                # Frontend UI
│   ├── index.html         # Wizard interface
│   ├── app.js             # Frontend controller
│   └── style.css          # Styles
├── bin/                   # Place EPA .exe files here
├── data/                  # Station inventories (auto-downloaded)
└── projects/              # Working directories for each run
```

## Manual Start (without launch.bat)

```bash
pip install -r requirements.txt
python server.py
```

Then open `http://localhost:5000` in your browser.

## Completeness Assessment

Data completeness is evaluated from the **final .SFC output file**, not raw
inputs. An hour is valid if it has real meteorological values (e.g., sensible
heat flux is not a missing-value code). **Calm wind hours (zero wind speed)
are valid** — they are not counted as missing. Completeness is checked on
the quarterly or annual basis you specify, and the tool warns you if any
year or quarter falls below your threshold.
