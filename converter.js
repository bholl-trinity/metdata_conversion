/**
 * GHCNh to ISD Converter - UI Handler
 * This file handles the browser UI and uses the ghcnh-to-isd.js module for conversion
 */

// Global state
let ghcnhData = null;
let isdOutput = null;
let inputPreview = '';
let outputPreview = '';
let currentFile = null;

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

// Initialize event listeners
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', handleDragOver);
dropZone.addEventListener('dragleave', handleDragLeave);
dropZone.addEventListener('drop', handleDrop);
fileInput.addEventListener('change', handleFileSelect);
convertBtn.addEventListener('click', startConversion);
downloadBtn.addEventListener('click', downloadISD);
resetBtn.addEventListener('click', resetApp);
mappingInfo.querySelector('h3').addEventListener('click', () => {
    mappingInfo.classList.toggle('expanded');
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
        }

        fileInfo.classList.add('visible');
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
 * Start the conversion process
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
    let converted = 0;
    let skipped = 0;
    const outputLines = [];

    // Process in chunks for responsiveness
    const chunkSize = 1000;
    const totalRecords = ghcnhData.records.length;

    for (let i = 0; i < totalRecords; i += chunkSize) {
        const chunk = ghcnhData.records.slice(i, i + chunkSize);

        for (const record of chunk) {
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

        // Update progress
        const progress = Math.min(100, Math.round(((i + chunk.length) / totalRecords) * 100));
        progressFill.style.width = progress + '%';
        progressText.textContent = `Converting... ${i + chunk.length} / ${totalRecords} records`;

        // Yield to UI
        await new Promise(resolve => setTimeout(resolve, 0));
    }

    const endTime = performance.now();
    const duration = ((endTime - startTime) / 1000).toFixed(2);

    isdOutput = outputLines.join('\n');

    // Update stats
    document.getElementById('statRecords').textContent = converted.toLocaleString();
    document.getElementById('statSkipped').textContent = skipped.toLocaleString();
    document.getElementById('statOutputSize').textContent = formatFileSize(isdOutput.length);
    document.getElementById('statTime').textContent = duration + 's';

    statsContainer.classList.add('visible');

    // Create output preview
    outputPreview = outputLines.slice(0, 10).join('\n');

    progressFill.style.width = '100%';
    progressText.textContent = 'Conversion complete!';

    downloadBtn.disabled = false;

    setTimeout(() => {
        progressContainer.classList.remove('visible');
    }, 1500);
}

/**
 * Download the converted ISD file
 */
function downloadISD() {
    if (!isdOutput) {
        showError('No converted data to download');
        return;
    }

    // Generate filename based on input
    let filename = 'converted.isd';
    if (currentFile) {
        // Try to extract station info from filename
        const match = currentFile.name.match(/GHCNh_(\w+)_/);
        if (match && ghcnhData && ghcnhData.records.length > 0) {
            const record = ghcnhData.records[0];
            const sourceId = record.temperature_Source_Station_ID || '';
            if (sourceId.includes('-') && !sourceId.includes('ICAO')) {
                filename = sourceId.replace('-', '') + '-converted';
            } else {
                filename = match[1] + '-converted';
            }
        }

        // Add year range
        if (ghcnhData && ghcnhData.records.length > 0) {
            const firstYear = ghcnhData.records[0].Year;
            const lastYear = ghcnhData.records[ghcnhData.records.length - 1].Year;
            if (firstYear === lastYear) {
                filename += '-' + firstYear;
            } else {
                filename += '-' + firstYear + '-' + lastYear;
            }
        }
    }

    const blob = new Blob([isdOutput], { type: 'text/plain' });
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
    inputPreview = '';
    outputPreview = '';
    currentFile = null;

    dropZone.classList.remove('has-file');
    fileInput.value = '';
    fileInfo.classList.remove('visible');
    progressContainer.classList.remove('visible');
    statsContainer.classList.remove('visible');
    previewContainer.classList.remove('visible');
    hideError();

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
