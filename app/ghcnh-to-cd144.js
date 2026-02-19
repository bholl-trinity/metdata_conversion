/**
 * GHCNh to CD144 Converter - Core Module
 * Converts Global Historical Climatology Network hourly (GHCNh) PSV files
 * to CD144 (.met) fixed-width format for AERMOD/ISC meteorological input
 *
 * CD144 format: 79 chars per line, one line per hour, local time,
 * one file per year with every hour represented (8760 or 8784 lines)
 *
 * This module depends on GHCNhToISD for: parseGHCNh, fillMissingSkyCover, buildStationIdMap
 */

(function(exports) {

/**
 * Main entry point: convert GHCNh PSV text to CD144 format
 * @param {string} ghcnhText - Raw PSV file text
 * @param {number} utcOffset - Signed hours from UTC (negative = west, e.g., -5 for US Eastern)
 * @param {string} inputFilename - Original input filename for output naming
 * @param {function} progressCallback - Optional (current, total) => void
 * @returns {{ files: Array<{year, output, filename}>, converted: number, skipped: number, total: number }}
 */
function convertGHCNhToCD144(ghcnhText, utcOffset, inputFilename, progressCallback) {
    // Step 1: Parse using shared function
    var data = GHCNhToISD.parseGHCNh(ghcnhText);

    // Step 2: Fill missing sky cover from nearby records
    GHCNhToISD.fillMissingSkyCover(data.records);

    // Step 3: Build station map and extract CD144 station ID
    var stationMap = GHCNhToISD.buildStationIdMap(data.records);
    var stationId = extractCD144StationId(data.records, stationMap);

    // Step 4: Compute local times for all records and find year range
    var yearsSet = {};
    var localTimes = [];
    for (var i = 0; i < data.records.length; i++) {
        var local = shiftToLocalTime(data.records[i], utcOffset);
        localTimes.push(local);
        yearsSet[local.year] = true;
    }

    var years = Object.keys(yearsSet).map(Number).sort();

    // Step 5: For each year, build grid, assign records, format lines
    var files = [];
    var converted = 0;
    var skipped = 0;
    var processed = 0;

    // Determine base filename (strip extension from input)
    var baseName = inputFilename ? inputFilename.replace(/\.[^/.]+$/, '') : 'output';

    for (var yi = 0; yi < years.length; yi++) {
        var year = years[yi];
        var grid = buildHourlyGrid(year);

        // Assign records to grid slots
        for (var ri = 0; ri < data.records.length; ri++) {
            var lt = localTimes[ri];
            if (lt.year !== year) continue;

            var idx = hourIndex(year, lt.month, lt.day, lt.hour);
            if (idx < 0 || idx >= grid.length) continue;

            var slot = grid[idx];
            if (slot.record === null) {
                slot.record = data.records[ri];
                slot._minute = lt.minute;
            } else {
                // Prefer observation closest to end of hour (highest minute)
                if (lt.minute > slot._minute) {
                    slot.record = data.records[ri];
                    slot._minute = lt.minute;
                }
            }
        }

        // Format all lines for this year
        var lines = [];
        for (var gi = 0; gi < grid.length; gi++) {
            var s = grid[gi];
            var line = formatCD144Line(stationId, s.year, s.month, s.day, s.hour, s.record);
            lines.push(line);

            if (s.record) {
                converted++;
            } else {
                skipped++;
            }

            processed++;
            if (progressCallback && processed % 2000 === 0) {
                progressCallback(processed, grid.length * years.length);
            }
        }

        // Determine filename
        var filename;
        if (years.length === 1) {
            filename = baseName + '.met';
        } else {
            filename = baseName + '_' + year + '.met';
        }

        files.push({
            year: year,
            output: lines.join('\n'),
            filename: filename
        });
    }

    return {
        files: files,
        converted: converted,
        skipped: skipped,
        total: data.records.length
    };
}

/**
 * Shift a GHCNh record's UTC time to local time
 */
function shiftToLocalTime(record, utcOffset) {
    var utcYear = parseInt(record.Year, 10) || 2000;
    var utcMonth = parseInt(record.Month, 10) || 1;
    var utcDay = parseInt(record.Day, 10) || 1;
    var utcHour = parseInt(record.Hour, 10) || 0;
    var utcMinute = parseInt(record.Minute, 10) || 0;

    // Use Date object as timezone-neutral arithmetic helper
    // All operations use UTC methods to avoid browser timezone interference
    var d = new Date(Date.UTC(utcYear, utcMonth - 1, utcDay, utcHour, utcMinute));
    d.setUTCHours(d.getUTCHours() + utcOffset + 1);

    return {
        year: d.getUTCFullYear(),
        month: d.getUTCMonth() + 1,
        day: d.getUTCDate(),
        hour: d.getUTCHours(),
        minute: utcMinute
    };
}

/**
 * Check if a year is a leap year
 */
function isLeapYear(year) {
    return (year % 4 === 0 && year % 100 !== 0) || (year % 400 === 0);
}

/**
 * Build an array of hourly slots for every hour of a given year
 */
function buildHourlyGrid(year) {
    var grid = [];
    var daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

    for (var m = 0; m < 12; m++) {
        for (var d = 1; d <= daysInMonth[m]; d++) {
            for (var h = 0; h < 24; h++) {
                grid.push({
                    year: year,
                    month: m + 1,
                    day: d,
                    hour: h,
                    record: null,
                    _minute: -1
                });
            }
        }
    }
    return grid;
}

/**
 * Convert a local date/time to a 0-based index into the hourly grid
 */
function hourIndex(year, month, day, hour) {
    var daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    var idx = 0;
    for (var m = 0; m < month - 1; m++) {
        idx += daysInMonth[m] * 24;
    }
    idx += (day - 1) * 24;
    idx += hour;
    return idx;
}

/**
 * Extract the 5-digit station ID for CD144 (first 5 chars of 6-digit USAF ID)
 */
function extractCD144StationId(records, stationMap) {
    if (records.length === 0) return '99999';

    var ghcnhId = records[0].Station_ID;
    if (stationMap && stationMap[ghcnhId]) {
        var usaf = stationMap[ghcnhId].usaf; // e.g., "725190"
        return usaf.slice(0, 5); // e.g., "72519"
    }
    return '99999';
}

// ============================================================
// Unit Conversion and Formatting Functions
// ============================================================

/**
 * Format temperature or dewpoint: Celsius -> whole Fahrenheit, 3 chars
 * Negative values use "X" prefix: -4F -> "X04"
 * Returns 3 spaces if missing
 */
function formatCD144Temperature(tempC) {
    if (tempC === undefined || tempC === null || tempC === '') return '   ';
    var num = parseFloat(tempC);
    if (isNaN(num)) return '   ';

    var f = Math.round(num * 9 / 5 + 32);

    if (f < 0) {
        var absF = Math.min(Math.abs(f), 99); // Clamp to 2 digits after sign
        return '-' + String(absF).padStart(2, '0');
    }
    return String(f).padStart(3, '0');
}

/**
 * Format wind direction: round to nearest 10 degrees, divide by 10, 2 chars
 * Calm winds = "00", missing = "  " (2 spaces)
 */
function formatCD144WindDirection(dirDeg, measurementCode) {
    // Calm winds
    if (measurementCode && measurementCode.includes('C-Calm')) {
        return '00';
    }

    if (!dirDeg || dirDeg === '' || dirDeg === '999') return '  ';

    var num = parseInt(dirDeg, 10);
    if (isNaN(num) || num < 0 || num > 360) return '  ';

    // Round to nearest 10, then divide by 10
    var tens = Math.round(num / 10);
    // 0 degrees maps to 36 (north = 360)
    if (tens === 0) tens = 36;
    return String(tens).padStart(2, '0');
}

/**
 * Format wind speed: m/s -> knots, whole number, 2 chars
 * Returns "  " if missing
 */
function formatCD144WindSpeed(speedMs) {
    if (!speedMs || speedMs === '') return '  ';
    var num = parseFloat(speedMs);
    if (isNaN(num)) return '  ';

    var knots = Math.round(num * 1.94384);
    return String(knots).padStart(2, '0');
}

/**
 * Format station pressure: hPa -> inHg x 100, 4 digits
 * Returns "    " if missing
 */
function formatCD144StationPressure(pressureHpa) {
    if (!pressureHpa || pressureHpa === '') return '    ';
    var num = parseFloat(pressureHpa);
    if (isNaN(num)) return '    ';

    var inHg100 = Math.round(num * 2.953);
    return String(inHg100).padStart(4, '0');
}

/**
 * Format ceiling height: lowest BKN/OVC/VV layer, meters -> feet / 100, 3 chars
 * Returns "   " if no ceiling (FEW/SCT only or clear)
 */
function formatCD144CeilingHeight(record) {
    var coverFields = [
        { cover: record.sky_cover_1, height: record.sky_cover_baseht_1 },
        { cover: record.sky_cover_2, height: record.sky_cover_baseht_2 },
        { cover: record.sky_cover_3, height: record.sky_cover_baseht_3 }
    ];

    // Find the lowest BKN/OVC/VV layer (first one found, since they're ordered low to high)
    for (var i = 0; i < coverFields.length; i++) {
        var field = coverFields[i];
        if (field.cover && (field.cover.includes('BKN') || field.cover.includes('OVC') || field.cover.includes('VV'))) {
            if (field.height && field.height !== '') {
                var heightM = parseInt(field.height.replace(/^\+/, ''), 10);
                if (!isNaN(heightM) && heightM >= 0) {
                    var heightFt = heightM * 3.28084;
                    var hundreds = Math.round(heightFt / 100);
                    return String(hundreds).padStart(3, '0');
                }
            }
        }
    }

    return '   '; // No ceiling
}

/**
 * Format relative humidity: use direct field if available, Magnus formula fallback
 * Returns "   " if missing
 */
function formatCD144RelativeHumidity(record) {
    // Prefer directly reported RH
    var rh = record.relative_humidity;
    if (rh && rh !== '') {
        var num = parseFloat(rh);
        if (!isNaN(num) && num >= 0 && num <= 100) {
            return String(Math.round(num)).padStart(3, '0');
        }
    }

    // Fallback: calculate from temperature and dewpoint using Magnus formula
    var tempC = parseFloat(record.temperature);
    var dewC = parseFloat(record.dew_point_temperature);
    if (isNaN(tempC) || isNaN(dewC)) return '   ';

    var rhCalc = 100 * (
        Math.exp((17.625 * dewC) / (243.04 + dewC)) /
        Math.exp((17.625 * tempC) / (243.04 + tempC))
    );
    var rhRound = Math.round(Math.min(100, Math.max(0, rhCalc)));
    return String(rhRound).padStart(3, '0');
}

/**
 * Format total cloud cover in tenths (0-9, "-" for 100% overcast)
 * Takes maximum oktas from any cloud layer
 * Returns "0" (clear) if no cloud data (e.g. CAVOK hours)
 */
function formatCD144CloudCover(record) {
    var coverFields = [record.sky_cover_1, record.sky_cover_2, record.sky_cover_3];
    var maxOktas = -1;
    var hasAnyCover = false;

    for (var i = 0; i < coverFields.length; i++) {
        var cover = coverFields[i];
        if (!cover || cover === '') continue;
        hasAnyCover = true;

        var oktas = parseOktas(cover);
        if (oktas > maxOktas) maxOktas = oktas;
    }

    if (!hasAnyCover) return '0'; // No cloud layers reported = clear sky (e.g. CAVOK)

    if (maxOktas === 8) return '-'; // 100% overcast
    if (maxOktas <= 0) return '0'; // Clear

    // Convert oktas to tenths: round(oktas * 10 / 8)
    var tenths = Math.round(maxOktas * 10 / 8);
    if (tenths > 9) tenths = 9;
    return String(tenths);
}

/**
 * Parse oktas from a sky cover string like "BKN:07", "OVC:08", "CLR:00"
 */
function parseOktas(cover) {
    if (!cover) return 0;

    if (cover.includes('CLR') || cover.includes(':00')) return 0;
    if (cover.includes('FEW:01')) return 1;
    if (cover.includes('FEW:02') || cover.includes('FEW')) return 2;
    if (cover.includes('SCT:03')) return 3;
    if (cover.includes('SCT:04') || cover.includes('SCT')) return 4;
    if (cover.includes('BKN:05')) return 5;
    if (cover.includes('BKN:06')) return 6;
    if (cover.includes('BKN:07') || cover.includes('BKN')) return 7;
    if (cover.includes('OVC:08') || cover.includes('OVC')) return 8;
    if (cover.includes('VV')) return 8; // Vertical visibility = overcast equivalent

    return 0;
}

// ============================================================
// Line Formatting
// ============================================================

/**
 * Format a single 79-character CD144 line
 * @param {string} stationId - 5-digit station ID
 * @param {number} year - 4-digit year
 * @param {number} month - 1-12
 * @param {number} day - 1-31
 * @param {number} hour - 0-23
 * @param {Object|null} record - GHCNh record or null for missing hour
 * @returns {string} 79-character CD144 line
 */
function formatCD144Line(stationId, year, month, day, hour, record) {
    // Columns 1-5: Station ID
    var stn = stationId.slice(0, 5).padStart(5, '0');

    // Columns 6-7: 2-digit year
    var yy = String(year).slice(-2);

    // Columns 8-9: month
    var mm = String(month).padStart(2, '0');

    // Columns 10-11: day
    var dd = String(day).padStart(2, '0');

    // Columns 12-13: hour
    var hh = String(hour).padStart(2, '0');

    // Date/time header (13 chars)
    var header = stn + yy + mm + dd + hh;

    if (!record) {
        // No data: station ID + date/time + all blanks to 79 chars
        return header + ' '.repeat(79 - 13);
    }

    // Columns 14-16: Ceiling height (3 chars)
    var ceiling = formatCD144CeilingHeight(record);

    // Columns 17-35: Always blank (19 spaces)
    var blank1 = '                   ';

    // Columns 36-38: Dewpoint temperature (3 chars)
    var dewpoint = formatCD144Temperature(record.dew_point_temperature);

    // Columns 39-40: Wind direction (2 chars)
    var windDir = formatCD144WindDirection(record.wind_direction, record.wind_direction_Measurement_Code);

    // Columns 41-42: Wind speed in knots (2 chars)
    var windSpd = formatCD144WindSpeed(record.wind_speed);

    // Columns 43-46: Station pressure inHg x 100 (4 chars)
    var pressure = formatCD144StationPressure(record.station_level_pressure);

    // Columns 47-49: Temperature (3 chars)
    var temp = formatCD144Temperature(record.temperature);

    // Columns 50-52: Always blank (3 spaces)
    var blank2 = '   ';

    // Columns 53-55: Relative humidity (3 chars)
    var rh = formatCD144RelativeHumidity(record);

    // Column 56: Total cloud cover (1 char)
    var cloud = formatCD144CloudCover(record);

    // Columns 57-79: Padding (23 spaces)
    var blank3 = '                       ';

    var line = header + ceiling + blank1 + dewpoint + windDir + windSpd + pressure + temp + blank2 + rh + cloud + blank3;

    // Safety: ensure exactly 79 chars
    if (line.length < 79) {
        line = line + ' '.repeat(79 - line.length);
    } else if (line.length > 79) {
        line = line.slice(0, 79);
    }

    return line;
}

// Export functions
exports.convertGHCNhToCD144 = convertGHCNhToCD144;

})(typeof exports !== 'undefined' ? exports : (window.GHCNhToCD144 = {}));
