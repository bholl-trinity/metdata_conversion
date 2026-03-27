# Meteorological Data Conversion Toolkit

Tools for preparing meteorological input files for EPA's AERMET/AERMOD air
dispersion modeling system. Automates downloading, converting, and preprocessing
weather data from NOAA/NCEI.

## Components

### AERMET Automation Tool (`aermet/`)

A locally-run web application that automates the entire AERMET workflow: enter a
location and the tool discovers stations, downloads data, runs EPA utilities, and
produces production-ready .SFC and .PFL files.

**Quick start:** See [`aermet/README.md`](aermet/README.md)

### Rust Rewrite (`aermet-tool/`)

Same tool compiled to a single binary — no Python required. In progress.
See [`docs/rust-rewrite-plan.md`](docs/rust-rewrite-plan.md)

### Client-Side Converter (`app/`)

Browser-based GHCNh format converter deployed to GitHub Pages. Converts GHCNh
to ISD or CD144 format entirely in the browser. Includes a gap-fill tool for
CD144 files.

### CLI Upper Air Tools (root)

Standalone scripts for upper air data:

| Script | Purpose |
|--------|---------|
| `igra_to_fsl.py` | Convert IGRA v2 format to FSL text format |
| `igra_fsl_tool.py` | Download IGRA data by station call sign and convert to FSL |
| `uwyo_to_fsl.py` | Download soundings from University of Wyoming and convert to FSL |

## Data Flow

```
NOAA/NCEI Data Sources          Conversion              EPA Utilities        Output
─────────────────────          ──────────              ─────────────        ──────
GHCNh (surface obs)  ──→  ISD (fixed-width)  ──→
                                                       AERMET Stage 1-3  ──→  .SFC
IGRA (upper air)     ──→  (read natively)    ──→                          ──→  .PFL

NLCD GeoTIFF         ──→  AERSURFACE         ──→  surface params  ──→  (fed to Stage 3)

1-min ASOS           ──→  AERMINUTE          ──→  wind data       ──→  (fed to Stage 3)
```

## Documentation

- **[`CLAUDE.md`](CLAUDE.md)** — Complete project context for AI assistants
- **[`docs/Conversion Notes.md`](docs/Conversion%20Notes.md)** — Authoritative format conversion reference
- **[`docs/aermet-automation-plan.md`](docs/aermet-automation-plan.md)** — Full design specification
- **[`docs/rust-rewrite-plan.md`](docs/rust-rewrite-plan.md)** — Rust rewrite strategy

## Requirements

- **Python 3.8+** (for `aermet/` and CLI tools)
- **EPA executables** (`aermet.exe`, `aersurface.exe`, `aerminute.exe`) from
  [EPA SCRAM](https://www.epa.gov/scram/air-quality-dispersion-modeling-related-model-support-programs)
- Python packages: `flask`, `requests`, `certifi`
