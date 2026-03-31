#!/usr/bin/env python3
"""
IGRA/FSL Converter — Flask GUI

Simple web interface for converting upper air sounding data to FSL format.
Wraps the existing CLI tools: igra_to_fsl.py, igra_fsl_tool.py, uwyo_to_fsl.py.

Usage:
    python server.py
    # Opens http://localhost:5001
"""

import io
import os
import sys
import threading
import time
import tempfile
import shutil
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory

# Add parent directory so we can import the converter modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from igra_to_fsl import read_igra_soundings, filter_by_date, write_fsl_sounding, extract_wmo_number
from igra_fsl_tool import download_igra_data, lookup_station_metadata, trim_igra_to_years, convert_igra_to_fsl_by_year, resolve_station

app = Flask(__name__, static_folder='static', static_url_path='')

# In-memory job tracking
_jobs = {}
_jobs_lock = threading.Lock()

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# =========================================================================
# Tool 1: IGRA file upload → FSL conversion
# =========================================================================

@app.route('/api/convert-file', methods=['POST'])
def convert_file():
    """Convert an uploaded IGRA v2 file to FSL format."""
    if 'file' not in request.files:
        return jsonify(error="No file uploaded"), 400

    f = request.files['file']
    if not f.filename:
        return jsonify(error="No file selected"), 400

    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    wban = request.form.get('wban') or None
    name = request.form.get('name') or None
    lat = request.form.get('lat') or None
    lon = request.form.get('lon') or None
    elev = request.form.get('elev') or None
    classic_fsl = bool(request.form.get('classic_fsl'))
    thin = bool(request.form.get('thin'))

    # Parse dates
    from datetime import datetime
    sd = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    ed = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    # Build station metadata
    station_meta = {}
    if wban:
        station_meta['wban'] = wban
    if name:
        station_meta['name'] = name
    if lat:
        station_meta['lat'] = float(lat)
    if lon:
        station_meta['lon'] = float(lon)
    if elev:
        station_meta['elev'] = float(elev)

    # Save uploaded file to temp location
    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, 'input.txt')
    f.save(input_path)

    output_filename = (name or 'output') + '.fsl'
    output_path = os.path.join(job_dir, output_filename)

    # Convert
    try:
        soundings = read_igra_soundings(input_path)
        if sd or ed:
            soundings = filter_by_date(soundings, sd, ed)

        success = 0
        skipped = 0
        with open(output_path, 'w') as out:
            for header, levels in soundings:
                wrote = write_fsl_sounding(out, header, levels, station_meta, classic=classic_fsl, thin=thin)
                if wrote:
                    success += 1
                else:
                    skipped += 1

        if success == 0:
            return jsonify(error="No soundings converted. Check file and date range."), 400

        return jsonify(
            job_id=job_id,
            filename=output_filename,
            soundings_written=success,
            soundings_skipped=skipped,
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


# =========================================================================
# Tool 2: IGRA download + convert (background job)
# =========================================================================

@app.route('/api/download-convert', methods=['POST'])
def download_convert():
    """Download IGRA data from NCEI and convert to FSL (runs in background)."""
    data = request.get_json()
    if not data:
        return jsonify(error="JSON body required"), 400

    station = data.get('station', '').strip()
    name = data.get('name', '').strip()
    start_year = data.get('start_year')
    end_year = data.get('end_year')

    if not station or not start_year or not end_year:
        return jsonify(error="station, start_year, end_year are required"), 400

    start_year = int(start_year)
    end_year = int(end_year)

    # Resolve short call signs (e.g. "DTX") to full IGRA IDs
    try:
        igra_id, call_sign, resolved_wban = resolve_station(station)
        station = igra_id
    except SystemExit:
        return jsonify(error=f"Could not resolve station '{data.get('station')}' to an IGRA ID. "
                       "Try the full IGRA ID (e.g. USM00072632)."), 400

    # Auto-derive output name from call sign if not provided
    if not name:
        if call_sign:
            name = call_sign
        else:
            name = extract_wmo_number(station)

    classic_fsl = data.get('classic_fsl', False)
    thin = data.get('thin', False)

    if end_year < start_year:
        return jsonify(error="end_year must be >= start_year"), 400

    station_meta_overrides = {}
    for key in ('wban', 'lat', 'lon', 'elev'):
        val = data.get(key)
        if val is not None and val != '':
            station_meta_overrides[key] = float(val) if key in ('lat', 'lon', 'elev') else val

    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    with _jobs_lock:
        _jobs[job_id] = {
            'status': 'running',
            'step': 'Starting...',
            'error': None,
            'files': [],
            'stats': {},
        }

    def run_job():
        try:
            job = _jobs[job_id]

            # Step 1: Lookup metadata
            job['step'] = 'Looking up station metadata...'
            igra_meta = lookup_station_metadata(station)

            station_meta = {
                'name': name.upper(),
                'wmo': extract_wmo_number(station),
            }
            for k, v in station_meta_overrides.items():
                station_meta[k] = v
            # Auto-populate WBAN from ISD history if not provided by user
            if 'wban' not in station_meta:
                if resolved_wban:
                    station_meta['wban'] = resolved_wban
                else:
                    from igra_fsl_tool import _lookup_wban_by_wmo
                    wmo_num = extract_wmo_number(station)
                    if wmo_num:
                        looked_up = _lookup_wban_by_wmo(wmo_num)
                        if looked_up:
                            station_meta['wban'] = looked_up
            if 'lat' not in station_meta and 'lat' in igra_meta:
                station_meta['lat'] = igra_meta['lat']
            if 'lon' not in station_meta and 'lon' in igra_meta:
                station_meta['lon'] = igra_meta['lon']
            if 'elev' not in station_meta and 'elev' in igra_meta:
                station_meta['elev'] = igra_meta['elev']

            # Step 2: Download
            job['step'] = 'Downloading IGRA data from NCEI (this may take a minute)...'
            igra_full = os.path.join(job_dir, f'{station}-data.txt')
            download_igra_data(station, igra_full)

            # Step 3: Trim
            job['step'] = f'Trimming to {start_year}-{end_year}...'
            igra_trimmed = os.path.join(job_dir, f'{station}_trimmed.txt')
            stats = trim_igra_to_years(igra_full, igra_trimmed, start_year, end_year)

            if stats['kept_soundings'] == 0:
                job['status'] = 'error'
                job['error'] = f'No soundings found for {start_year}-{end_year}'
                return

            # Step 4: Convert
            job['step'] = 'Converting to FSL format...'
            result = convert_igra_to_fsl_by_year(
                igra_trimmed, job_dir, name, station_meta, start_year, end_year,
                classic=classic_fsl, thin=thin
            )

            # Build file list
            files = []
            for year in sorted(result['year_counts'].keys()):
                yy = f"{year % 100:02d}"
                fn = f"{name.upper()}{yy}.rao"
                files.append({
                    'filename': fn,
                    'soundings': result['year_counts'][year],
                    'size_kb': round(os.path.getsize(os.path.join(job_dir, fn)) / 1024, 1),
                })
            if start_year != end_year:
                combined_fn = os.path.basename(result['combined_path'])
                files.append({
                    'filename': combined_fn,
                    'soundings': result['combined_count'],
                    'size_kb': round(os.path.getsize(result['combined_path']) / 1024, 1),
                    'combined': True,
                })

            # Cleanup intermediate files
            for p in [igra_full, igra_trimmed]:
                if os.path.exists(p):
                    os.remove(p)

            job['status'] = 'complete'
            job['step'] = 'Done'
            job['files'] = files
            job['stats'] = {
                'total_soundings': stats['total_soundings'],
                'kept_soundings': stats['kept_soundings'],
                'converted': result['combined_count'],
            }

        except Exception as e:
            _jobs[job_id]['status'] = 'error'
            _jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()

    return jsonify(job_id=job_id)


@app.route('/api/job/<job_id>')
def job_status(job_id):
    """Poll job status."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify(error="Job not found"), 404
    return jsonify(**job)


# =========================================================================
# Tool 3: Wyoming download + convert (background job)
# =========================================================================

@app.route('/api/wyoming-convert', methods=['POST'])
def wyoming_convert():
    """Download Wyoming upper air data and convert to FSL (runs in background)."""
    data = request.get_json()
    if not data:
        return jsonify(error="JSON body required"), 400

    station = data.get('station', '').strip()
    start = data.get('start', '').strip()
    end = data.get('end', '').strip()
    both_hours = data.get('both_hours', False)
    hour = int(data.get('hour', 12))

    if not station or not start or not end:
        return jsonify(error="station, start, end are required"), 400

    station_meta = {}
    for key in ('wban', 'name', 'lat', 'lon', 'elev'):
        val = data.get(key)
        if val is not None and val != '':
            station_meta[key] = float(val) if key in ('lat', 'lon', 'elev') else val

    classic_fsl = data.get('classic_fsl', False)

    if 'name' not in station_meta:
        station_meta['name'] = station
    if 'wban' not in station_meta:
        from igra_fsl_tool import _lookup_wban_by_wmo
        looked_up = _lookup_wban_by_wmo(station)
        station_meta['wban'] = looked_up if looked_up else '99999'
    for k in ('lat', 'lon', 'elev'):
        if k not in station_meta:
            station_meta[k] = 0.0

    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    with _jobs_lock:
        _jobs[job_id] = {
            'status': 'running',
            'step': 'Starting...',
            'progress': 0,
            'error': None,
            'files': [],
            'stats': {},
        }

    def run_job():
        import requests as req_lib
        from datetime import datetime, timedelta
        from uwyo_to_fsl import parse_csv_sounding, write_fsl_sounding as uwyo_write_fsl, download_sounding

        try:
            job = _jobs[job_id]

            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")

            hours = [0, 12] if both_hours else [hour]
            total_days = (end_date - start_date).days + 1
            total_requests = total_days * len(hours)

            output_fn = f"{station}_{start}_{end}.fsl"
            output_path = os.path.join(job_dir, output_fn)

            session = req_lib.Session()
            session.headers.update({
                "User-Agent": "AERMET-FSL-Converter/1.0 (air quality research)"
            })

            success_count = 0
            fail_count = 0
            request_num = 0

            with open(output_path, 'w') as outfile:
                current_date = start_date
                while current_date <= end_date:
                    for h in hours:
                        dt = current_date.replace(hour=h)
                        request_num += 1
                        pct = round((request_num / total_requests) * 100, 1)

                        job['step'] = f'Downloading {dt.strftime("%Y-%m-%d %HZ")}...'
                        job['progress'] = pct

                        csv_text = download_sounding(station, dt, session)

                        if csv_text:
                            levels = parse_csv_sounding(csv_text)
                            if levels and len(levels) >= 3:
                                wrote = uwyo_write_fsl(outfile, levels, station, dt, station_meta, classic=classic_fsl)
                                if wrote:
                                    success_count += 1
                                else:
                                    fail_count += 1
                            else:
                                fail_count += 1
                        else:
                            fail_count += 1

                        time.sleep(1.5)

                    current_date += timedelta(days=1)

            if success_count == 0:
                job['status'] = 'error'
                job['error'] = 'No soundings retrieved. Check station and date range.'
                return

            size_kb = round(os.path.getsize(output_path) / 1024, 1)
            job['status'] = 'complete'
            job['step'] = 'Done'
            job['progress'] = 100
            job['files'] = [{'filename': output_fn, 'soundings': success_count, 'size_kb': size_kb}]
            job['stats'] = {'written': success_count, 'missing': fail_count}

        except Exception as e:
            _jobs[job_id]['status'] = 'error'
            _jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()

    return jsonify(job_id=job_id)


# =========================================================================
# File download
# =========================================================================

@app.route('/api/download/<job_id>/<filename>')
def download_file(job_id, filename):
    """Download a result file."""
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    filepath = os.path.join(job_dir, filename)
    if not os.path.exists(filepath):
        return jsonify(error="File not found"), 404
    return send_file(filepath, as_attachment=True, download_name=filename)


# =========================================================================
# Entry point
# =========================================================================

if __name__ == '__main__':
    import webbrowser

    port = int(os.environ.get('PORT', 5001))
    print(f"Starting IGRA/FSL Converter GUI on http://localhost:{port}")
    webbrowser.open(f'http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
