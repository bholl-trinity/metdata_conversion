# AERMET Automation Tool — Rust Rewrite Plan

## Goal

Rewrite the Python/Flask backend as a single Rust binary that:
- Launches instantly, no runtime dependencies
- Serves the same browser-based UI (HTML/JS/CSS embedded in the binary)
- Bundles aermet.exe, aersurface.exe, aerminute.exe inside the binary
- Produces a single distributable file (~10-15MB) per platform
- Cross-compiles from one machine to Windows, Mac, Linux

## Why Rust (native, not WASM)

- Single static binary, no installer needed
- No antivirus false positives (unlike PyInstaller)
- Sub-second startup
- Cross-compilation supported
- The codebase is ~3,000 lines of Python — manageable rewrite scope

## What Stays the Same

The **entire frontend** (index.html, app.js, style.css) is reused as-is. The API
contract between frontend and backend stays identical. From the user's perspective,
the app looks and behaves exactly the same — it just launches faster and doesn't
need Python installed.

## Architecture

```
aermet-tool/                     (Rust project)
├── Cargo.toml
├── src/
│   ├── main.rs                  # Entry point: start server, open browser
│   ├── server.rs                # HTTP server (axum routes)
│   ├── geocode.rs               # Address/airport/latlon → coordinates
│   ├── stations.rs              # Station discovery (GHCNh, ISD, IGRA)
│   ├── download.rs              # Data download orchestration
│   ├── ghcnh_to_isd.rs          # GHCNh PSV → ISD format converter
│   ├── igra.rs                  # IGRA download, parse, trim
│   ├── aermet_runner.rs         # Control file generation & subprocess exec
│   ├── aerminute.rs             # AERMINUTE control file & execution
│   ├── aersurface.rs            # AERSURFACE control file & execution
│   ├── completeness.rs          # SFC file completeness assessment
│   ├── project.rs               # Project state management (JSON)
│   └── http_client.rs           # Shared HTTP client (reqwest)
├── static/                      # Embedded at compile time
│   ├── index.html               # (copied from current frontend, unchanged)
│   ├── app.js                   # (unchanged)
│   └── style.css                # (unchanged)
├── data/
│   └── airports.csv             # Embedded at compile time
└── bin/                         # EPA executables, extracted on first run
    ├── aermet.exe
    ├── aersurface.exe
    └── aerminute.exe
```

## Rust Crate Dependencies

| Crate | Replaces | Purpose |
|-------|----------|---------|
| **axum** | Flask | HTTP server, routing, JSON responses |
| **tokio** | threading | Async runtime for concurrent operations |
| **reqwest** | requests | HTTP client for NOAA/EPA downloads |
| **serde / serde_json** | json | Serialize/deserialize project state & API |
| **rust-embed** | Flask static | Embed HTML/JS/CSS/CSV in binary at compile time |
| **csv** | csv module | Parse airports.csv, ISD station list |
| **zip** | zipfile | Create output ZIPs, extract IGRA archives |
| **chrono** | datetime | Date/time handling |
| **open** | webbrowser | Open browser on startup |
| **tokio::process** | subprocess | Run aermet.exe, aersurface.exe |
| **include_dir** | — | Embed EPA executables in binary |

## Module-by-Module Rewrite Plan

### Phase 1: Project Skeleton & Server (Day 1)

1. **Initialize Cargo project** with workspace structure
2. **main.rs** — Find free port, start axum server, open default browser
3. **server.rs** — Mount all route handlers, serve embedded static files
4. **Embed static assets** — index.html, app.js, style.css via rust-embed

Milestone: User double-clicks binary → browser opens → sees the UI (no backend logic yet)

### Phase 2: Core Infrastructure (Day 2)

4. **http_client.rs** — Shared reqwest client with timeouts, streaming downloads
5. **project.rs** — Project creation, state persistence (serde_json to/from project.json)
6. **geocode.rs** — Nominatim API calls, airport CSV lookup (embedded), haversine math

API endpoints working: `/api/geocode`, `/api/project/create`, `/api/project/{id}`

### Phase 3: Station Discovery (Day 3)

7. **stations.rs** — Download & parse GHCNh station list (fixed-width), ISD history (CSV),
   IGRA station list (fixed-width). Distance filtering, completeness checking.

API endpoints: `/api/stations/surface`, `/api/stations/upperair`, `/api/init`

### Phase 4: Data Download & Conversion (Days 4-5)

8. **download.rs** — Orchestrate downloads with progress callbacks via channels
9. **ghcnh_to_isd.rs** — Port the PSV→ISD fixed-width converter (most complex parsing)
10. **igra.rs** — Download, unzip, parse headers, trim by year range

API endpoints: `/api/project/{id}/download-data`, `/api/project/{id}/progress`

### Phase 5: AERMET Pipeline (Days 6-7)

11. **aermet_runner.rs** — Generate Stage 1/2/3 control files, run aermet.exe via
    tokio::process::Command, parse message files, combine multi-year outputs
12. **aerminute.rs** — Generate control file, run aerminute.exe
13. **aersurface.rs** — Generate control file, run aersurface.exe, reference values

API endpoints: `/api/project/{id}/run-aermet`, `/api/project/{id}/aersurface`,
`/api/aersurface/reference`

### Phase 6: Results & Packaging (Day 8)

14. **completeness.rs** — Parse SFC files, calculate quarterly/monthly/annual stats
15. **ZIP download** — Package output files

API endpoints: `/api/project/{id}/completeness`, `/api/project/{id}/download`

### Phase 7: Build & Distribution (Day 9-10)

16. **Embed EPA executables** — aermet.exe, aersurface.exe, aerminute.exe extracted
    to a temp directory on first run
17. **Cross-compile** — Build for Windows (primary target), Mac, Linux
18. **Test end-to-end** on Windows with real AERMET workflow
19. **GitHub Releases** — CI pipeline to build and upload per-platform binaries

## Progress Tracking & Background Tasks

The current Python app uses threading + in-memory progress dicts. In Rust:

- **tokio::spawn** replaces `threading.Thread`
- **tokio::sync::broadcast** channel replaces the progress dict — server sends
  progress events, the `/progress` endpoint receives them
- Same polling pattern from frontend (every 1.5s) works unchanged

## Executable Bundling Strategy

EPA executables (aermet.exe, etc.) are Windows-only .exe files. Strategy:

1. At compile time, embed them in the binary via `include_bytes!`
2. On first run, extract to `~/.aermet-tool/bin/` (or a temp dir)
3. Check SHA256 hash to avoid re-extracting on subsequent runs
4. Run via `tokio::process::Command` pointing to extracted path

This keeps the single-binary distribution model while working with the EPA's
Windows executables.

## Estimated Binary Size

| Component | Size |
|-----------|------|
| Rust binary (release, stripped) | ~5-8 MB |
| Embedded static files (HTML/JS/CSS) | ~50 KB |
| Embedded airports.csv | ~1 MB |
| Embedded aermet.exe + aersurface.exe + aerminute.exe | ~3-5 MB |
| **Total** | **~10-15 MB** |

## What Changes for the User

**Before (Python):**
```
1. Install Python
2. pip install flask requests certifi
3. python server.py
4. Open browser to localhost:5000
```

**After (Rust):**
```
1. Double-click aermet-tool.exe
```

That's it. Browser opens automatically. No install, no dependencies, no terminal.

## Risk & Mitigation

| Risk | Mitigation |
|------|------------|
| GHCNh parser is complex | Port line-by-line from Python, test against sample files |
| EPA .exe only runs on Windows | Mac/Linux builds skip AERMET execution, or use Wine |
| Fixed-width parsing is tedious | Rust's string slicing is actually great for this |
| Async complexity | axum + tokio is well-documented, battle-tested |
| Cross-compile to Windows | `cross` or `cargo-zigbuild` handles this reliably |

## Future Possibilities (not in scope now)

- Auto-update checker (ping GitHub releases API on startup)
- Portable mode (store projects next to .exe instead of home dir)
- Dark mode toggle in UI
- Multi-project dashboard
