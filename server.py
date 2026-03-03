"""
AERMET Automation Tool — Flask Backend Server

Serves the frontend UI and exposes API endpoints for the full AERMET
preprocessing workflow: geocode → stations → download → quality check
→ AERSURFACE → AERMINUTE → final AERMET run → output.
"""

import json
import os
import sys
import threading
import time
import traceback
import zipfile

from flask import Flask, jsonify, request, send_file, send_from_directory

# Ensure the core package is importable
sys.path.insert(0, os.path.dirname(__file__))

from core.geocode import geocode_address, geocode_airport, geocode_latlon, haversine_km
from core.stations import (
    find_nearby_surface_stations,
    find_nearby_upper_air_stations,
    ensure_isd_station_list,
    ensure_igra_station_list,
)
from core.download import (
    download_and_convert_surface,
    download_and_trim_upper_air,
    download_one_minute_asos,
)
from core.project import create_project, load_project, update_project
from core.aermet_runner import (
    run_aermet_all_stages,
    combine_sfc_files,
    combine_pfl_files,
)
from core.completeness import compute_completeness, check_completeness
from core.aersurface import (
    generate_control_file as gen_aersurface_ctrl,
    run_aersurface,
    LAND_USE_REFERENCE,
)
from core.aerminute import (
    generate_control_file as gen_aerminute_ctrl,
    run_aerminute,
    check_aerminute_availability,
)

app = Flask(__name__, static_folder='static', static_url_path='')

# In-memory progress tracking for long-running operations
_progress = {}
_progress_lock = threading.Lock()


def _set_progress(project_id, stage, message, detail=None):
    """Thread-safe progress update."""
    with _progress_lock:
        if project_id not in _progress:
            _progress[project_id] = []
        _progress[project_id].append({
            'stage': stage,
            'message': message,
            'detail': detail,
            'time': time.time(),
        })


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

@app.route('/api/geocode', methods=['POST'])
def api_geocode():
    data = request.json
    method = data.get('method', 'address')
    try:
        if method == 'address':
            result = geocode_address(data['address'])
        elif method == 'airport':
            result = geocode_airport(data['code'])
        elif method == 'latlon':
            result = geocode_latlon(data['lat'], data['lon'])
        else:
            return jsonify({'error': f'Unknown method: {method}'}), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------

@app.route('/api/stations/surface', methods=['GET'])
def api_surface_stations():
    lat = float(request.args['lat'])
    lon = float(request.args['lon'])
    start_year = int(request.args['start_year'])
    end_year = int(request.args['end_year'])
    max_dist = float(request.args.get('max_distance', 150))

    try:
        stations = find_nearby_surface_stations(lat, lon, start_year, end_year, max_dist)
        return jsonify(stations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stations/upperair', methods=['GET'])
def api_upper_air_stations():
    lat = float(request.args['lat'])
    lon = float(request.args['lon'])
    start_year = int(request.args['start_year'])
    end_year = int(request.args['end_year'])
    max_dist = float(request.args.get('max_distance', 400))

    try:
        stations = find_nearby_upper_air_stations(lat, lon, start_year, end_year, max_dist)
        return jsonify(stations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------------

@app.route('/api/project/create', methods=['POST'])
def api_create_project():
    data = request.json
    try:
        project = create_project(
            location=data['location'],
            data_period=data['data_period'],
            completeness=data['completeness'],
            is_us=data.get('is_us', True),
        )
        return jsonify(project)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/project/<project_id>', methods=['GET'])
def api_get_project(project_id):
    try:
        return jsonify(load_project(project_id))
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/project/<project_id>/update', methods=['POST'])
def api_update_project(project_id):
    data = request.json
    try:
        project = load_project(project_id)
        project = update_project(project, **data)
        return jsonify(project)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Data download & processing (long-running, background tasks)
# ---------------------------------------------------------------------------

@app.route('/api/project/<project_id>/download-data', methods=['POST'])
def api_download_data(project_id):
    """
    Start downloading surface + upper air data.
    Runs in a background thread; poll /api/project/<id>/progress for status.
    """
    data = request.json
    project = load_project(project_id)

    def _run():
        try:
            pid = project_id

            def pcb(stage, msg):
                _set_progress(pid, stage, msg)

            # Store station selections
            sf = data.get('surface_station', {})
            ua = data.get('upper_air_station', {})
            start_year = project['data_period']['start_year']
            end_year = project['data_period']['end_year']

            update_project(project,
                           surface_station=sf,
                           upper_air_station=ua,
                           status='downloading')

            # Download surface data (GHCNh → ISD)
            _set_progress(pid, 'surface', 'Downloading surface data...')
            ghcnh_station_id = sf.get('ghcnh_id', '')
            if not ghcnh_station_id:
                # Construct GHCNh station ID from USAF/WBAN
                usaf = sf.get('usaf', '')
                wban = sf.get('wban', '')
                # GHCNh IDs are typically USW000XXXXX format
                ghcnh_station_id = f"USW00{wban}" if wban and wban != '99999' else usaf

            surface_dir = os.path.join(project['dir'], 'surface')
            surface_result = download_and_convert_surface(
                ghcnh_station_id, surface_dir, pcb)

            update_project(project, results={
                **project.get('results', {}),
                'surface': {
                    'isd_path': surface_result['isd_path'],
                    'stats': surface_result['stats'],
                },
            })

            # Download upper air data (IGRA)
            _set_progress(pid, 'upper_air', 'Downloading upper air data...')
            ua_dir = os.path.join(project['dir'], 'upper_air')
            ua_result = download_and_trim_upper_air(
                ua['id'], ua_dir, start_year, end_year, pcb)

            update_project(project, results={
                **project.get('results', {}),
                'upper_air': {
                    'igra_path': ua_result['igra_path'],
                    'stats': ua_result['stats'],
                },
            })

            # Download 1-minute ASOS if applicable
            onemin_files = {}
            if project.get('is_us') and sf.get('wban') and sf['wban'] != '99999':
                wban = sf['wban']
                if check_aerminute_availability(wban, start_year, end_year):
                    onemin_dir = os.path.join(project['dir'], 'one_minute')
                    for yr in range(start_year, end_year + 1):
                        path = download_one_minute_asos(wban, yr, onemin_dir, pcb)
                        if path:
                            onemin_files[yr] = path

            update_project(project, results={
                **project.get('results', {}),
                'onemin_files': onemin_files,
            }, status='downloaded')

            _set_progress(pid, 'complete', 'All data downloaded successfully')

        except Exception as e:
            _set_progress(project_id, 'error', str(e))
            update_project(project, status='error',
                           errors=project.get('errors', []) + [str(e)])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({'status': 'started', 'message': 'Download started'})


# ---------------------------------------------------------------------------
# AERMET execution
# ---------------------------------------------------------------------------

@app.route('/api/project/<project_id>/run-aermet', methods=['POST'])
def api_run_aermet(project_id):
    """
    Run the full AERMET pipeline (stages 1-3) for all years.
    Background task.
    """
    data = request.json or {}
    project = load_project(project_id)

    def _run():
        try:
            pid = project_id

            def pcb(stage, msg):
                _set_progress(pid, stage, msg)

            update_project(project, status='running_aermet')

            sf = project['surface_station']
            ua = project['upper_air_station']
            start_year = project['data_period']['start_year']
            end_year = project['data_period']['end_year']

            results_data = project.get('results', {})
            isd_path = results_data.get('surface', {}).get('isd_path', '')
            igra_path = results_data.get('upper_air', {}).get('igra_path', '')
            onemin_files = results_data.get('onemin_files', {})

            # Surface station info for AERMET
            sf_id = sf.get('usaf', '999999') + sf.get('wban', '99999')
            sf_lat = sf.get('refined_lat', sf.get('lat', 0))
            sf_lon = sf.get('refined_lon', sf.get('lon', 0))
            ua_id = ua.get('id', '')
            ua_lat = ua.get('lat', 0)
            ua_lon = ua.get('lon', 0)

            # Surface characteristics
            aersurface_file = data.get('aersurface_file')
            manual_chars = data.get('manual_surface_chars')
            anemometer_height = float(data.get('anemometer_height', 10.0))

            aermet_dir = os.path.join(project['dir'], 'aermet')
            os.makedirs(os.path.join(aermet_dir, 'output'), exist_ok=True)

            sfc_files = []
            pfl_files = []
            year_results = {}

            for yr in range(start_year, end_year + 1):
                _set_progress(pid, 'aermet', f'Processing year {yr}...')

                onemin = onemin_files.get(str(yr))

                result = run_aermet_all_stages(
                    aermet_dir, yr, isd_path, igra_path,
                    sf_id, sf_lat, sf_lon,
                    ua_id, ua_lat, ua_lon,
                    aersurface_file=aersurface_file,
                    onemin_file=onemin,
                    anemometer_height=anemometer_height,
                    manual_surface_chars=manual_chars,
                    progress_cb=pcb,
                )

                year_results[yr] = result

                if result['success']:
                    sfc_files.append(result['sfc_path'])
                    pfl_files.append(result['pfl_path'])

                    # Assess completeness from the SFC output
                    comp = check_completeness(
                        result['sfc_path'],
                        threshold=project['completeness']['threshold'],
                        basis=project['completeness']['basis'],
                        full_year=yr,
                    )
                    year_results[yr]['completeness'] = comp

                    if not comp['passes']:
                        _set_progress(pid, 'warning',
                                      f'Year {yr} below completeness threshold: '
                                      + '; '.join(comp['failures']))

            # Combine multi-year files
            output_dir = os.path.join(project['dir'], 'output')
            os.makedirs(output_dir, exist_ok=True)

            output_option = data.get('output_option', 'both')
            final_files = {}

            if output_option in ('combined', 'both') and len(sfc_files) > 1:
                combined_sfc = os.path.join(output_dir, 'combined.SFC')
                combined_pfl = os.path.join(output_dir, 'combined.PFL')
                combine_sfc_files(sfc_files, combined_sfc)
                combine_pfl_files(pfl_files, combined_pfl)
                final_files['combined_sfc'] = combined_sfc
                final_files['combined_pfl'] = combined_pfl

            if output_option in ('individual', 'both'):
                for yr in range(start_year, end_year + 1):
                    yr_result = year_results.get(yr, {})
                    if yr_result.get('success'):
                        final_files[f'{yr}_sfc'] = yr_result['sfc_path']
                        final_files[f'{yr}_pfl'] = yr_result['pfl_path']

            update_project(project,
                           status='complete',
                           results={
                               **results_data,
                               'year_results': {str(k): _sanitize(v) for k, v in year_results.items()},
                               'final_files': final_files,
                           })

            _set_progress(pid, 'complete', 'AERMET processing complete')

        except Exception as e:
            _set_progress(project_id, 'error', f'AERMET error: {e}\n{traceback.format_exc()}')
            update_project(project, status='error',
                           errors=project.get('errors', []) + [str(e)])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({'status': 'started', 'message': 'AERMET processing started'})


def _sanitize(obj):
    """Make dict JSON-serializable (remove non-serializable items)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()
                if not callable(v)}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(x) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# Progress polling
# ---------------------------------------------------------------------------

@app.route('/api/project/<project_id>/progress', methods=['GET'])
def api_progress(project_id):
    since = float(request.args.get('since', 0))
    with _progress_lock:
        entries = _progress.get(project_id, [])
        new_entries = [e for e in entries if e['time'] > since]
    return jsonify(new_entries)


# ---------------------------------------------------------------------------
# Completeness results
# ---------------------------------------------------------------------------

@app.route('/api/project/<project_id>/completeness', methods=['GET'])
def api_completeness(project_id):
    project = load_project(project_id)
    results = project.get('results', {})
    year_results = results.get('year_results', {})

    completeness_data = {}
    for yr_str, yr_data in year_results.items():
        if 'completeness' in yr_data:
            completeness_data[yr_str] = yr_data['completeness']

    return jsonify(completeness_data)


# ---------------------------------------------------------------------------
# AERSURFACE
# ---------------------------------------------------------------------------

@app.route('/api/project/<project_id>/aersurface', methods=['POST'])
def api_aersurface(project_id):
    data = request.json
    project = load_project(project_id)
    work_dir = os.path.join(project['dir'], 'aermet')

    try:
        ctrl = gen_aersurface_ctrl(
            work_dir=work_dir,
            nlcd_path=data['nlcd_path'],
            center_lat=float(data['center_lat']),
            center_lon=float(data['center_lon']),
            is_airport=data.get('is_airport', True),
        )
        result = run_aersurface(ctrl, work_dir)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/aersurface/reference', methods=['GET'])
def api_land_use_reference():
    return jsonify(LAND_USE_REFERENCE)


# ---------------------------------------------------------------------------
# Download output files
# ---------------------------------------------------------------------------

@app.route('/api/project/<project_id>/download', methods=['GET'])
def api_download_output(project_id):
    """Download all output files as a ZIP archive."""
    project = load_project(project_id)
    results = project.get('results', {})
    final_files = results.get('final_files', {})

    if not final_files:
        return jsonify({'error': 'No output files available'}), 404

    zip_path = os.path.join(project['dir'], 'output', 'aermet_output.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for label, fpath in final_files.items():
            if os.path.exists(fpath):
                arcname = os.path.basename(fpath)
                zf.write(fpath, arcname)

    return send_file(zip_path, as_attachment=True,
                     download_name='aermet_output.zip')


@app.route('/api/project/<project_id>/download/<filename>', methods=['GET'])
def api_download_file(project_id, filename):
    """Download a specific output file."""
    project = load_project(project_id)
    output_dir = os.path.join(project['dir'], 'output')
    return send_from_directory(output_dir, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Station list pre-caching
# ---------------------------------------------------------------------------

@app.route('/api/init', methods=['POST'])
def api_init():
    """Pre-download station inventories on first load."""
    try:
        ensure_isd_station_list()
        ensure_igra_station_list()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Create directories
    os.makedirs(os.path.join(os.path.dirname(__file__), 'projects'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'data'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'bin'), exist_ok=True)

    print('=' * 60)
    print('  AERMET Automation Tool')
    print('  Starting server at http://localhost:5000')
    print('=' * 60)
    print()
    print('  Open your browser to: http://localhost:5000')
    print()
    print('  Press Ctrl+C to stop the server.')
    print('=' * 60)

    import webbrowser
    webbrowser.open('http://localhost:5000')

    app.run(host='127.0.0.1', port=5000, debug=False)
