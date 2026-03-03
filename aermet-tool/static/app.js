/**
 * AERMET Automation Tool — Frontend Controller
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
    currentStep: 1,
    project: null,
    location: null,
    surfaceStations: [],
    upperAirStations: [],
    selectedSurface: null,
    selectedUpperAir: null,
    refinedLat: null,
    refinedLon: null,
    map: null,
    marker: null,
    pollTimer: null,
    lastProgressTime: 0,
};

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function goToStep(n) {
    document.querySelectorAll('.step-section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(`step-${n}`);
    if (target) target.classList.add('active');

    document.querySelectorAll('.step-item').forEach(el => {
        const step = parseInt(el.dataset.step);
        el.classList.remove('active', 'completed');
        if (step === n) el.classList.add('active');
        else if (step < n) el.classList.add('completed');
    });

    state.currentStep = n;
    window.scrollTo(0, 0);
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function api(url, opts = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
}

function post(url, body) {
    return api(url, { method: 'POST', body: JSON.stringify(body) });
}

// ---------------------------------------------------------------------------
// Step 1: Location & Setup
// ---------------------------------------------------------------------------

// Location method toggle
document.querySelectorAll('input[name="loc-method"]').forEach(el => {
    el.addEventListener('change', () => {
        document.getElementById('loc-address').classList.toggle('hidden', el.value !== 'address');
        document.getElementById('loc-latlon').classList.toggle('hidden', el.value !== 'latlon');
        document.getElementById('loc-airport').classList.toggle('hidden', el.value !== 'airport');
    });
});

document.getElementById('btn-geocode').addEventListener('click', async () => {
    const btn = document.getElementById('btn-geocode');
    btn.disabled = true;
    btn.textContent = 'Locating...';

    try {
        const method = document.querySelector('input[name="loc-method"]:checked').value;
        let payload = { method };

        if (method === 'address') {
            payload.address = document.getElementById('address').value;
            if (!payload.address) throw new Error('Please enter an address');
        } else if (method === 'latlon') {
            payload.lat = parseFloat(document.getElementById('lat').value);
            payload.lon = parseFloat(document.getElementById('lon').value);
            if (isNaN(payload.lat) || isNaN(payload.lon)) throw new Error('Please enter valid coordinates');
        } else if (method === 'airport') {
            payload.code = document.getElementById('icao').value.trim().toUpperCase();
            if (!payload.code || payload.code.length < 3) throw new Error('Please enter a valid ICAO code');
        }

        // Geocode
        state.location = await post('/api/geocode', payload);
        const loc = state.location;

        const resultEl = document.getElementById('geocode-result');
        resultEl.classList.remove('hidden');
        resultEl.textContent = `Location: ${loc.display_name || loc.name || ''} (${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}) — ${loc.is_us ? 'US site' : 'Non-US site'}`;

        // Create project
        const numYears = parseInt(document.getElementById('num-years').value) || 5;
        const startYear = parseInt(document.getElementById('start-year').value) || 2019;
        const threshold = parseInt(document.getElementById('threshold').value) || 90;
        const basis = document.querySelector('input[name="basis"]:checked').value;

        state.project = await post('/api/project/create', {
            location: { lat: loc.lat, lon: loc.lon, display_name: loc.display_name || '' },
            data_period: { num_years: numYears, start_year: startYear },
            completeness: { threshold, basis },
            is_us: loc.is_us,
        });

        // Find stations
        const endYear = startYear + numYears - 1;
        const [surface, upperAir] = await Promise.all([
            api(`/api/stations/surface?lat=${loc.lat}&lon=${loc.lon}&start_year=${startYear}&end_year=${endYear}`),
            api(`/api/stations/upperair?lat=${loc.lat}&lon=${loc.lon}&start_year=${startYear}&end_year=${endYear}`),
        ]);

        state.surfaceStations = surface;
        state.upperAirStations = upperAir;

        renderSurfaceStations(surface);
        renderUpperAirStations(upperAir);

        // Auto-select first
        if (surface.length) selectSurfaceStation(0);
        if (upperAir.length) selectUpperAirStation(0);

        goToStep(2);
    } catch (err) {
        alert('Error: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Locate & Find Stations';
    }
});

// ---------------------------------------------------------------------------
// Step 2: Station Selection
// ---------------------------------------------------------------------------
function renderSurfaceStations(stations) {
    const tbody = document.querySelector('#surface-station-table tbody');
    tbody.innerHTML = '';
    stations.forEach((s, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="radio" name="sf-station" value="${i}"></td>
            <td>${s.name}</td>
            <td>${s.usaf}</td>
            <td>${s.wban}</td>
            <td>${s.icao || '-'}</td>
            <td>${s.distance_km}</td>
            <td>${s.first_year}–${s.last_year}</td>
        `;
        tr.addEventListener('click', () => selectSurfaceStation(i));
        tbody.appendChild(tr);
    });
}

function renderUpperAirStations(stations) {
    const tbody = document.querySelector('#ua-station-table tbody');
    tbody.innerHTML = '';
    stations.forEach((s, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="radio" name="ua-station" value="${i}"></td>
            <td>${s.name}</td>
            <td>${s.id}</td>
            <td>${s.distance_km}</td>
            <td>${s.elev != null ? s.elev : '-'}</td>
            <td>${s.first_year}–${s.last_year}</td>
        `;
        tr.addEventListener('click', () => selectUpperAirStation(i));
        tbody.appendChild(tr);
    });
}

function selectSurfaceStation(idx) {
    state.selectedSurface = state.surfaceStations[idx];
    // Highlight row
    document.querySelectorAll('#surface-station-table tbody tr').forEach((tr, i) => {
        tr.classList.toggle('selected', i === idx);
        const radio = tr.querySelector('input[type="radio"]');
        if (radio) radio.checked = (i === idx);
    });
    // Update coordinate refinement map
    initCoordinateMap(state.selectedSurface.lat, state.selectedSurface.lon);
}

function selectUpperAirStation(idx) {
    state.selectedUpperAir = state.upperAirStations[idx];
    document.querySelectorAll('#ua-station-table tbody tr').forEach((tr, i) => {
        tr.classList.toggle('selected', i === idx);
        const radio = tr.querySelector('input[type="radio"]');
        if (radio) radio.checked = (i === idx);
    });
}

// Coordinate refinement map
function initCoordinateMap(lat, lon) {
    const card = document.getElementById('coord-refine-card');
    card.classList.remove('hidden');

    state.refinedLat = lat;
    state.refinedLon = lon;
    document.getElementById('refined-lat').value = lat.toFixed(6);
    document.getElementById('refined-lon').value = lon.toFixed(6);

    if (state.map) {
        state.map.remove();
    }

    state.map = L.map('map').setView([lat, lon], 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(state.map);

    state.marker = L.marker([lat, lon], { draggable: true }).addTo(state.map);
    state.marker.on('dragend', () => {
        const pos = state.marker.getLatLng();
        state.refinedLat = pos.lat;
        state.refinedLon = pos.lng;
        document.getElementById('refined-lat').value = pos.lat.toFixed(6);
        document.getElementById('refined-lon').value = pos.lng.toFixed(6);
    });

    // Force map to resize properly
    setTimeout(() => state.map.invalidateSize(), 200);
}

document.getElementById('btn-reset-coords').addEventListener('click', () => {
    if (state.selectedSurface) {
        const { lat, lon } = state.selectedSurface;
        state.marker.setLatLng([lat, lon]);
        state.map.setView([lat, lon], 15);
        state.refinedLat = lat;
        state.refinedLon = lon;
        document.getElementById('refined-lat').value = lat.toFixed(6);
        document.getElementById('refined-lon').value = lon.toFixed(6);
    }
});

document.getElementById('btn-back-1').addEventListener('click', () => goToStep(1));

// ---------------------------------------------------------------------------
// Step 3: Download Data
// ---------------------------------------------------------------------------
document.getElementById('btn-to-download').addEventListener('click', async () => {
    if (!state.selectedSurface) { alert('Please select a surface station'); return; }
    if (!state.selectedUpperAir) { alert('Please select an upper air station'); return; }

    // Save refined coords
    const sf = { ...state.selectedSurface };
    sf.refined_lat = state.refinedLat || sf.lat;
    sf.refined_lon = state.refinedLon || sf.lon;
    // Construct a GHCNh station ID
    if (sf.wban && sf.wban !== '99999') {
        sf.ghcnh_id = 'USW00' + sf.wban;
    }

    goToStep(3);

    // Start download
    try {
        await post(`/api/project/${state.project.id}/download-data`, {
            surface_station: sf,
            upper_air_station: state.selectedUpperAir,
        });
        startProgressPoll('download-log', () => {
            document.getElementById('download-status').textContent = 'All data downloaded!';
            document.getElementById('download-status').className = 'alert alert-success';
            document.getElementById('btn-to-landuse').classList.remove('hidden');
        });
    } catch (err) {
        document.getElementById('download-status').textContent = 'Download error: ' + err.message;
        document.getElementById('download-status').className = 'alert alert-error';
    }
});

document.getElementById('btn-to-landuse').addEventListener('click', () => {
    // Show appropriate land use panel
    const isUs = state.project.is_us;
    document.getElementById('landuse-us').classList.toggle('hidden', !isUs);
    document.getElementById('landuse-manual').classList.toggle('hidden', isUs);
    goToStep(4);
});

// ---------------------------------------------------------------------------
// Progress polling
// ---------------------------------------------------------------------------
function startProgressPoll(logElId, onComplete) {
    state.lastProgressTime = 0;
    const logEl = document.getElementById(logElId);

    if (state.pollTimer) clearInterval(state.pollTimer);

    state.pollTimer = setInterval(async () => {
        try {
            const entries = await api(
                `/api/project/${state.project.id}/progress?since=${state.lastProgressTime}`
            );
            if (entries.length) {
                state.lastProgressTime = entries[entries.length - 1].time;
                entries.forEach(e => {
                    const div = document.createElement('div');
                    div.className = 'log-entry' + (e.stage === 'error' ? ' error' : '') + (e.stage === 'warning' ? ' warning' : '');
                    const t = new Date(e.time * 1000).toLocaleTimeString();
                    div.innerHTML = `<span class="log-time">${t}</span>${e.message}`;
                    logEl.appendChild(div);
                    logEl.scrollTop = logEl.scrollHeight;
                });

                // Check for completion
                const last = entries[entries.length - 1];
                if (last.stage === 'complete' || last.stage === 'error') {
                    clearInterval(state.pollTimer);
                    if (last.stage === 'complete' && onComplete) onComplete();
                }
            }
        } catch (e) {
            // Polling error, will retry
        }
    }, 1500);
}

// ---------------------------------------------------------------------------
// Step 4: Land Use
// ---------------------------------------------------------------------------

// Land use type reference values
document.getElementById('landuse-type').addEventListener('change', async (e) => {
    const type = e.target.value;
    if (!type) return;
    try {
        const ref = await api('/api/aersurface/reference');
        const vals = ref[type];
        if (vals) {
            document.getElementById('manual-albedo').value = vals.albedo;
            document.getElementById('manual-bowen').value = vals.bowen;
            document.getElementById('manual-roughness').value = vals.roughness;
        }
    } catch (err) {
        // Use defaults
    }
});

document.getElementById('btn-skip-aersurface').addEventListener('click', () => {
    goToStep(5);
    runAermet(null);
});

document.getElementById('btn-run-aersurface').addEventListener('click', async () => {
    const nlcdPath = document.getElementById('nlcd-path').value.trim();
    if (!nlcdPath) {
        alert('Please provide an NLCD file path, or click "Skip" to use defaults.');
        return;
    }
    try {
        const isAirport = document.querySelector('input[name="airport-flag"]:checked').value === 'true';
        const result = await post(`/api/project/${state.project.id}/aersurface`, {
            nlcd_path: nlcdPath,
            center_lat: state.refinedLat || state.selectedSurface.lat,
            center_lon: state.refinedLon || state.selectedSurface.lon,
            is_airport: isAirport,
        });
        if (result.success) {
            alert('AERSURFACE completed successfully!');
            goToStep(5);
            runAermet(result.output_path);
        } else {
            alert('AERSURFACE failed: ' + (result.error || 'Unknown error'));
        }
    } catch (err) {
        alert('AERSURFACE error: ' + err.message);
    }
});

document.getElementById('btn-back-3').addEventListener('click', () => goToStep(3));

document.getElementById('btn-to-aermet').addEventListener('click', () => {
    goToStep(5);

    // Gather surface characteristics
    let aersurfaceFile = null;
    let manualChars = null;

    if (!state.project.is_us || document.getElementById('landuse-manual').classList.contains('hidden') === false) {
        manualChars = {
            albedo: parseFloat(document.getElementById('manual-albedo').value) || 0.18,
            bowen: parseFloat(document.getElementById('manual-bowen').value) || 1.0,
            roughness: parseFloat(document.getElementById('manual-roughness').value) || 0.15,
        };
    }

    runAermet(aersurfaceFile, manualChars);
});

// ---------------------------------------------------------------------------
// Step 5: Run AERMET
// ---------------------------------------------------------------------------
async function runAermet(aersurfaceFile, manualChars) {
    const outputOption = document.querySelector('input[name="output-option"]:checked').value;
    const anemometerHeight = parseFloat(document.getElementById('anemometer-height').value) || 10.0;

    document.getElementById('aermet-status').textContent = 'Starting AERMET processing...';
    document.getElementById('aermet-status').className = 'alert alert-info';
    document.getElementById('aermet-log').innerHTML = '';

    try {
        await post(`/api/project/${state.project.id}/run-aermet`, {
            aersurface_file: aersurfaceFile,
            manual_surface_chars: manualChars,
            anemometer_height: anemometerHeight,
            output_option: outputOption,
        });
        startProgressPoll('aermet-log', () => {
            document.getElementById('aermet-status').textContent = 'AERMET processing complete!';
            document.getElementById('aermet-status').className = 'alert alert-success';
            document.getElementById('btn-to-results').classList.remove('hidden');
        });
    } catch (err) {
        document.getElementById('aermet-status').textContent = 'AERMET error: ' + err.message;
        document.getElementById('aermet-status').className = 'alert alert-error';
    }
}

document.getElementById('btn-to-results').addEventListener('click', async () => {
    goToStep(6);
    await loadResults();
});

// ---------------------------------------------------------------------------
// Step 6: Results
// ---------------------------------------------------------------------------
async function loadResults() {
    try {
        const project = await api(`/api/project/${state.project.id}`);
        state.project = project;

        const results = project.results || {};
        const yearResults = results.year_results || {};
        const finalFiles = results.final_files || {};
        const threshold = project.completeness.threshold;
        const basis = project.completeness.basis;

        // Completeness table
        const tbody = document.querySelector('#completeness-table tbody');
        tbody.innerHTML = '';
        const warningsDiv = document.getElementById('completeness-warnings');
        warningsDiv.innerHTML = '';

        const years = Object.keys(yearResults).sort();
        const allFailures = [];

        years.forEach(yr => {
            const yrData = yearResults[yr];
            const comp = yrData.completeness || {};
            const c = comp.completeness || {};
            const byQ = c.by_quarter || {};

            const tr = document.createElement('tr');
            const annPct = c.completeness_pct || 0;
            const q1 = byQ.Q1 || 0;
            const q2 = byQ.Q2 || 0;
            const q3 = byQ.Q3 || 0;
            const q4 = byQ.Q4 || 0;

            tr.innerHTML = `
                <td><strong>${yr}</strong></td>
                <td class="${pctClass(annPct, threshold)}">${annPct}%</td>
                <td class="${pctClass(q1, threshold)}">${q1}%</td>
                <td class="${pctClass(q2, threshold)}">${q2}%</td>
                <td class="${pctClass(q3, threshold)}">${q3}%</td>
                <td class="${pctClass(q4, threshold)}">${q4}%</td>
            `;
            tbody.appendChild(tr);

            // Collect failures
            const failures = (comp.failures || []);
            if (failures.length) {
                allFailures.push({ year: yr, failures });
            }
        });

        // Show completeness warnings
        if (allFailures.length) {
            const div = document.createElement('div');
            div.className = 'alert alert-warning';
            let html = '<strong>Completeness below threshold:</strong><ul style="margin:8px 0 0 20px;">';
            allFailures.forEach(f => {
                f.failures.forEach(msg => {
                    html += `<li>Year ${f.year}: ${msg}</li>`;
                });
            });
            html += '</ul>';
            div.innerHTML = html;
            warningsDiv.appendChild(div);
        }

        // Output files
        const filesDiv = document.getElementById('output-files');
        filesDiv.innerHTML = '';
        Object.entries(finalFiles).forEach(([label, path]) => {
            const fname = path.split(/[/\\]/).pop();
            const div = document.createElement('div');
            div.className = 'download-item';
            div.innerHTML = `
                <div>
                    <div class="file-name">${fname}</div>
                    <div class="file-desc">${label.replace(/_/g, ' ')}</div>
                </div>
                <a class="btn btn-outline" href="/api/project/${state.project.id}/download/${fname}">Download</a>
            `;
            filesDiv.appendChild(div);
        });

        // Summary
        const summaryDiv = document.getElementById('summary');
        const sf = project.surface_station || {};
        const ua = project.upper_air_station || {};
        summaryDiv.innerHTML = `
            <table style="font-size:0.85rem; width:100%;">
                <tr><td style="padding:4px 12px 4px 0; font-weight:500; color:var(--gray-500);">Surface Station</td>
                    <td>${sf.name || '-'} (${sf.usaf || '-'}/${sf.wban || '-'})</td></tr>
                <tr><td style="padding:4px 12px 4px 0; font-weight:500; color:var(--gray-500);">Upper Air Station</td>
                    <td>${ua.name || '-'} (${ua.id || '-'})</td></tr>
                <tr><td style="padding:4px 12px 4px 0; font-weight:500; color:var(--gray-500);">Period</td>
                    <td>${project.data_period.start_year} – ${project.data_period.end_year}</td></tr>
                <tr><td style="padding:4px 12px 4px 0; font-weight:500; color:var(--gray-500);">Completeness Threshold</td>
                    <td>${threshold}% (${basis})</td></tr>
                <tr><td style="padding:4px 12px 4px 0; font-weight:500; color:var(--gray-500);">Status</td>
                    <td>${project.status}</td></tr>
            </table>
        `;
    } catch (err) {
        console.error('Error loading results:', err);
    }
}

function pctClass(pct, threshold) {
    if (pct >= threshold) return 'pct-pass';
    if (pct >= threshold - 5) return 'pct-marginal';
    return 'pct-fail';
}

// ZIP download
document.getElementById('btn-download-zip').addEventListener('click', () => {
    if (state.project) {
        window.location.href = `/api/project/${state.project.id}/download`;
    }
});

// ---------------------------------------------------------------------------
// Init: pre-cache station lists
// ---------------------------------------------------------------------------
(async () => {
    try {
        await post('/api/init', {});
    } catch (e) {
        console.warn('Station list init failed (will download on demand):', e.message);
    }
})();
