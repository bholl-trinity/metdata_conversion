/**
 * GHCNh Format Converter - UI Handler
 * This file handles the browser UI and uses ghcnh-to-isd.js and ghcnh-to-cd144.js for conversion
 */

// Global state
let ghcnhData = null;
let isdOutput = null;
let cd144Files = null;
let inputPreview = '';
let outputPreview = '';
let currentFile = null;
let selectedFormat = 'isd';

// DOM Elements
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const progressContainer = document.getElementById('progressContainer');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const convertBtn = document.getElementById('convertBtn');
const downloadBtn = document.getElementById('downloadBtn');
const resetBtn = document.getElementById('resetBtn');
const errorMessage = document.getElementById('errorMessage');
const statsContainer = document.getElementById('statsContainer');
const previewContainer = document.getElementById('previewContainer');
const previewContent = document.getElementById('previewContent');
const mappingInfo = document.getElementById('mappingInfo');
const conversionOptions = document.getElementById('conversionOptions');
const outputFormatSelect = document.getElementById('outputFormat');
const cd144Options = document.getElementById('cd144Options');
const utcOffsetInput = document.getElementById('utcOffset');
const outputTab = document.getElementById('outputTab');

// Initialize event listeners
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', handleDragOver);
dropZone.addEventListener('dragleave', handleDragLeave);
dropZone.addEventListener('drop', handleDrop);
fileInput.addEventListener('change', handleFileSelect);
convertBtn.addEventListener('click', startConversion);
downloadBtn.addEventListener('click', downloadOutput);
resetBtn.addEventListener('click', resetApp);
mappingInfo.querySelector('h3').addEventListener('click', () => {
    mappingInfo.classList.toggle('expanded');
});

// Format selector
outputFormatSelect.addEventListener('change', function() {
    selectedFormat = this.value;
    if (selectedFormat === 'cd144') {
        convertBtn.textContent = 'Convert to CD144';
        outputTab.textContent = 'Output (CD144)';
    } else {
        convertBtn.textContent = 'Convert to ISD';
        outputTab.textContent = 'Output (ISD)';
    }
    // Reset output since format changed
    isdOutput = null;
    cd144Files = null;
    downloadBtn.disabled = true;
    statsContainer.classList.remove('visible');
});

// Tab switching
document.querySelectorAll('.preview-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.preview-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const tabName = tab.dataset.tab;
        previewContent.textContent = tabName === 'input' ? inputPreview : outputPreview;
    });
});

function handleDragOver(e) {
    e.preventDefault();
    dropZone.classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    dropZone.classList.remove('dragover');
}

function handleDrop(e) {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        processFile(files[0]);
    }
}

function handleFileSelect(e) {
    if (e.target.files.length > 0) {
        processFile(e.target.files[0]);
    }
}

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('visible');
}

function hideError() {
    errorMessage.classList.remove('visible');
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

async function processFile(file) {
    hideError();
    currentFile = file;

    // Validate file
    if (file.size > 100 * 1024 * 1024) {
        showError('File too large. Maximum size is 100 MB.');
        return;
    }

    dropZone.classList.add('has-file');
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileSize').textContent = formatFileSize(file.size);

    try {
        progressContainer.classList.add('visible');
        progressText.textContent = 'Reading file...';
        progressFill.style.width = '10%';

        const text = await file.text();
        progressFill.style.width = '30%';
        progressText.textContent = 'Parsing GHCNh data...';

        // Parse the GHCNh file using the module
        ghcnhData = GHCNhToISD.parseGHCNh(text);

        // Fill in missing sky_cover data from previous records within 45 minutes
        GHCNhToISD.fillMissingSkyCover(ghcnhData.records);

        progressFill.style.width = '100%';
        progressText.textContent = 'File loaded successfully!';

        // Update file info
        if (ghcnhData.records.length > 0) {
            const firstRecord = ghcnhData.records[0];
            const lastRecord = ghcnhData.records[ghcnhData.records.length - 1];

            document.getElementById('stationId').textContent = firstRecord.Station_ID || '-';
            document.getElementById('stationName').textContent = firstRecord.Station_name || '-';
            document.getElementById('recordCount').textContent = ghcnhData.records.length.toLocaleString();

            const startDate = `${firstRecord.Year}-${String(firstRecord.Month).padStart(2, '0')}-${String(firstRecord.Day).padStart(2, '0')}`;
            const endDate = `${lastRecord.Year}-${String(lastRecord.Month).padStart(2, '0')}-${String(lastRecord.Day).padStart(2, '0')}`;
            document.getElementById('dateRange').textContent = `${startDate} to ${endDate}`;

            // Auto-suggest most recent complete year for year range fields
            const lastFullYear = lastRecord.Month === 12 && lastRecord.Day === 31
                ? lastRecord.Year : lastRecord.Year - 1;
            document.getElementById('endYear').placeholder = lastFullYear;
            document.getElementById('startYear').placeholder = lastFullYear;
        }

        fileInfo.classList.add('visible');
        conversionOptions.classList.add('visible');
        convertBtn.disabled = false;

        // Create input preview
        const lines = text.split('\n').slice(0, 10);
        inputPreview = lines.join('\n');
        previewContent.textContent = inputPreview;
        previewContainer.classList.add('visible');

        setTimeout(() => {
            progressContainer.classList.remove('visible');
        }, 1000);

    } catch (err) {
        showError('Error parsing file: ' + err.message);
        progressContainer.classList.remove('visible');
    }
}

/**
 * Start the conversion process - branches by selected format
 */
async function startConversion() {
    if (!ghcnhData || ghcnhData.records.length === 0) {
        showError('No data to convert');
        return;
    }

    hideError();
    convertBtn.disabled = true;
    progressContainer.classList.add('visible');
    progressFill.style.width = '0%';
    progressText.textContent = 'Converting records...';

    const startTime = performance.now();

    if (selectedFormat === 'cd144') {
        await startCD144Conversion(startTime);
    } else {
        await startISDConversion(startTime);
    }
}

/**
 * Build a UTC date range filter that includes the full UTC year(s) plus
 * extra hours from the adjacent year so AERMET has a complete year in
 * local standard time.
 *
 * Western hemisphere (utcOffset < 0): pad END into next year.
 *   e.g. UTC-6 for 2025: include Jan 1 2026 hours 00-05 UTC
 * Eastern hemisphere (utcOffset > 0): pad START from previous year.
 *   e.g. UTC+8 for 2025: include Dec 31 2024 hours 16-23 UTC
 *
 * Returns { startUTC: Date, endUTC: Date } or null if no filtering.
 */
function buildDateFilter(startYear, endYear, utcOffset) {
    if (!startYear || !endYear) return null;

    // Base: full UTC year range
    const startUTC = new Date(Date.UTC(startYear, 0, 1, 0, 0));    // Jan 1 00:00 UTC
    const endUTC   = new Date(Date.UTC(endYear, 11, 31, 23, 59));   // Dec 31 23:59 UTC

    if (utcOffset < 0) {
        // Western hemisphere: last local hour of Dec 31 = Jan 1 at hour |offset|-1 UTC
        endUTC.setTime(Date.UTC(endYear + 1, 0, 1, Math.abs(utcOffset) - 1, 59));
    } else if (utcOffset > 0) {
        // Eastern hemisphere: first local hour of Jan 1 = Dec 31 at hour 24-offset UTC
        startUTC.setTime(Date.UTC(startYear - 1, 11, 31, 24 - utcOffset, 0));
    }

    return { startUTC, endUTC };
}

/**
 * Check if a GHCNh record falls within the date filter range.
 */
function recordInRange(record, filter) {
    if (!filter) return true;
    const recUTC = Date.UTC(record.Year, record.Month - 1, record.Day, record.Hour || 0, record.Minute || 0);
    return recUTC >= filter.startUTC.getTime() && recUTC <= filter.endUTC.getTime();
}

/**
 * ISD conversion with optional year range + timezone padding
 */
async function startISDConversion(startTime) {
    let converted = 0;
    let skipped = 0;
    let filtered = 0;
    const outputLines = [];

    // Read year range and UTC offset
    const startYearVal = document.getElementById('startYear').value;
    const endYearVal = document.getElementById('endYear').value;
    const utcOffset = parseInt(document.getElementById('utcOffset').value, 10) || 0;

    const startYear = startYearVal ? parseInt(startYearVal, 10) : null;
    const endYear = endYearVal ? parseInt(endYearVal, 10) : (startYear || null);

    const dateFilter = buildDateFilter(startYear, endYear, utcOffset);

    if (dateFilter) {
        const padDesc = utcOffset < 0
            ? `+ first ${Math.abs(utcOffset)}h of ${endYear + 1}`
            : utcOffset > 0
                ? `+ last ${utcOffset}h of ${startYear - 1}`
                : '';
        progressText.textContent = `Filtering to ${startYear}-${endYear} UTC ${padDesc}...`;
    }

    const chunkSize = 1000;
    const totalRecords = ghcnhData.records.length;

    for (let i = 0; i < totalRecords; i += chunkSize) {
        const chunk = ghcnhData.records.slice(i, i + chunkSize);

        for (const record of chunk) {
            if (!recordInRange(record, dateFilter)) {
                filtered++;
                continue;
            }
            try {
                const isdLine = GHCNhToISD.convertRecordToISD(record);
                if (isdLine) {
                    outputLines.push(isdLine);
                    converted++;
                } else {
                    skipped++;
                }
            } catch (err) {
                skipped++;
            }
        }

        const progress = Math.min(100, Math.round(((i + chunk.length) / totalRecords) * 100));
        progressFill.style.width = progress + '%';
        progressText.textContent = `Converting... ${i + chunk.length} / ${totalRecords} records`;

        await new Promise(resolve => setTimeout(resolve, 0));
    }

    const endTime = performance.now();
    const duration = ((endTime - startTime) / 1000).toFixed(2);

    isdOutput = outputLines.join('\n');
    cd144Files = null;

    let recordsLabel = converted.toLocaleString();
    if (filtered > 0) {
        recordsLabel += ` (${filtered.toLocaleString()} outside range)`;
    }
    document.getElementById('statRecords').textContent = recordsLabel;
    document.getElementById('statSkipped').textContent = skipped.toLocaleString();
    document.getElementById('statOutputSize').textContent = formatFileSize(isdOutput.length);
    document.getElementById('statTime').textContent = duration + 's';

    statsContainer.classList.add('visible');

    outputPreview = outputLines.slice(0, 10).join('\n');

    progressFill.style.width = '100%';
    progressText.textContent = 'Conversion complete!';
    downloadBtn.disabled = false;

    setTimeout(() => {
        progressContainer.classList.remove('visible');
    }, 1500);
}

/**
 * CD144 conversion
 */
async function startCD144Conversion(startTime) {
    const utcOffset = parseInt(utcOffsetInput.value, 10);
    if (isNaN(utcOffset) || utcOffset < -12 || utcOffset > 14) {
        showError('Please enter a valid UTC offset between -12 and +14');
        convertBtn.disabled = false;
        progressContainer.classList.remove('visible');
        return;
    }

    progressText.textContent = 'Reading file for CD144 conversion...';
    progressFill.style.width = '10%';

    try {
        const text = await currentFile.text();
        const inputFilename = currentFile ? currentFile.name : 'output.met';

        const result = GHCNhToCD144.convertGHCNhToCD144(text, utcOffset, inputFilename, function(current, total) {
            const pct = Math.min(100, Math.round((current / total) * 100));
            progressFill.style.width = pct + '%';
            progressText.textContent = 'Building CD144 hourly grid... ' + pct + '%';
        });

        const endTime = performance.now();
        const duration = ((endTime - startTime) / 1000).toFixed(2);

        cd144Files = result.files;
        isdOutput = null;

        let recordsText = result.converted.toLocaleString();
        if (result.files.length > 1) {
            recordsText += ' (' + result.files.length + ' files)';
        }
        document.getElementById('statRecords').textContent = recordsText;
        document.getElementById('statSkipped').textContent = result.skipped.toLocaleString();

        const totalSize = result.files.reduce(function(sum, f) { return sum + f.output.length; }, 0);
        document.getElementById('statOutputSize').textContent = formatFileSize(totalSize);
        document.getElementById('statTime').textContent = duration + 's';

        statsContainer.classList.add('visible');

        outputPreview = result.files[0].output.split('\n').slice(0, 10).join('\n');

        progressFill.style.width = '100%';
        progressText.textContent = 'Conversion complete!';
        downloadBtn.disabled = false;

        setTimeout(() => {
            progressContainer.classList.remove('visible');
        }, 1500);

    } catch (err) {
        showError('CD144 conversion error: ' + err.message);
        progressContainer.classList.remove('visible');
        convertBtn.disabled = false;
    }
}

/**
 * Download the converted output file(s)
 */
function downloadOutput() {
    if (selectedFormat === 'cd144') {
        downloadCD144();
    } else {
        downloadISD();
    }
}

/**
 * Download the converted ISD file
 */
function downloadISD() {
    if (!isdOutput) {
        showError('No converted data to download');
        return;
    }

    let filename = 'converted.ish';
    if (currentFile) {
        const baseName = currentFile.name.replace(/\.[^/.]+$/, '');
        const startYearVal = document.getElementById('startYear').value;
        const endYearVal = document.getElementById('endYear').value;
        if (startYearVal) {
            const sy = startYearVal;
            const ey = endYearVal || sy;
            filename = baseName + '_' + sy + (ey !== sy ? '-' + ey : '') + '.ish';
        } else {
            filename = baseName + '.ish';
        }
    }

    downloadBlob(isdOutput, filename);
}

/**
 * Download CD144 file(s)
 */
function downloadCD144() {
    if (!cd144Files || cd144Files.length === 0) {
        showError('No converted data to download');
        return;
    }

    if (cd144Files.length === 1) {
        downloadBlob(cd144Files[0].output, cd144Files[0].filename);
    } else {
        // Multiple files: download each with a small delay
        for (let i = 0; i < cd144Files.length; i++) {
            const file = cd144Files[i];
            setTimeout(function() {
                downloadBlob(file.output, file.filename);
            }, i * 500);
        }
    }
}

/**
 * Helper: trigger browser download of text content
 */
function downloadBlob(content, filename) {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Reset the application state
 */
function resetApp() {
    ghcnhData = null;
    isdOutput = null;
    cd144Files = null;
    inputPreview = '';
    outputPreview = '';
    currentFile = null;

    dropZone.classList.remove('has-file');
    fileInput.value = '';
    fileInfo.classList.remove('visible');
    conversionOptions.classList.remove('visible');
    progressContainer.classList.remove('visible');
    statsContainer.classList.remove('visible');
    previewContainer.classList.remove('visible');
    hideError();

    // Reset format selection
    selectedFormat = 'isd';
    outputFormatSelect.value = 'isd';
    cd144Options.style.display = 'none';
    convertBtn.textContent = 'Convert to ISD';
    outputTab.textContent = 'Output (ISD)';

    convertBtn.disabled = true;
    downloadBtn.disabled = true;

    document.getElementById('fileName').textContent = '-';
    document.getElementById('fileSize').textContent = '-';
    document.getElementById('stationId').textContent = '-';
    document.getElementById('stationName').textContent = '-';
    document.getElementById('recordCount').textContent = '-';
    document.getElementById('dateRange').textContent = '-';

    progressFill.style.width = '0%';
}
