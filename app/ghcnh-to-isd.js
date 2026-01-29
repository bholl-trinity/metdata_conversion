/**
 * GHCNh to ISD Converter - Core Module
 * Converts Global Historical Climatology Network hourly (GHCNh) PSV files
 * to Integrated Surface Data (ISD) fixed-width format
 *
 * This module can be used in both browser and Node.js environments
 */

(function(exports) {

/**
 * Parse GHCNh PSV file
 */
function parseGHCNh(text) {
    const lines = text.split('\n').filter(line => line.trim());
    if (lines.length < 2) {
        throw new Error('File appears to be empty or invalid');
    }

    // Parse header
    const headers = lines[0].split('|');
    const records = [];

    // Parse data lines
    for (let i = 1; i < lines.length; i++) {
        const values = lines[i].split('|');
        const record = {};

        for (let j = 0; j < headers.length && j < values.length; j++) {
            record[headers[j]] = values[j];
        }

        records.push(record);
    }

    return { headers, records };
}

/**
 * Convert a single GHCNh record to ISD format
 * @param {Object} record - The GHCNh record to convert
 * @param {Object} stationMap - Optional map of Station_ID to {usaf, wban}
 */
function convertRecordToISD(record, stationMap) {
    // Extract station IDs from the source
    let usafId = '999999';
    let wbanId = '99999';

    // First, check if we have a pre-built mapping for this station
    const ghcnhId = record.Station_ID;
    if (stationMap && stationMap[ghcnhId]) {
        usafId = stationMap[ghcnhId].usaf;
        wbanId = stationMap[ghcnhId].wban;
    } else {
        // Try to extract from current record's source station IDs
        const stationIdFields = [
            'temperature_Source_Station_ID',
            'wind_direction_Source_Station_ID',
            'wind_speed_Source_Station_ID',
            'sea_level_pressure_Source_Station_ID',
            'station_level_pressure_Source_Station_ID',
            'visibility_Source_Station_ID',
            'dew_point_temperature_Source_Station_ID',
            'altimeter_Source_Station_ID',
            'sky_cover_1_Source_Station_ID'
        ];

        for (const field of stationIdFields) {
            const sourceStationId = record[field] || '';
            if (sourceStationId.includes('-') && !sourceStationId.includes('ICAO')) {
                const parts = sourceStationId.split('-');
                if (parts.length === 2 && parts[0].length >= 5 && parts[1].length >= 4) {
                    usafId = parts[0].padStart(6, '0').slice(0, 6);
                    wbanId = parts[1].padStart(5, '0').slice(0, 5);
                    break;
                }
            }
        }

        // If still not found, extract WBAN from GHCNh Station_ID (USWnnnnnnnn format)
        if (usafId === '999999' && ghcnhId) {
            if (ghcnhId.startsWith('USW') && ghcnhId.length >= 11) {
                // USW00014771 -> WBAN is 14771
                wbanId = ghcnhId.slice(6, 11);
            }
        }
    }

    // Date and time
    const year = String(record.Year || '9999').padStart(4, '0');
    const month = String(record.Month || '99').padStart(2, '0');
    const day = String(record.Day || '99').padStart(2, '0');
    const hour = String(record.Hour || '99').padStart(2, '0');
    const minute = String(record.Minute || '99').padStart(2, '0');
    const date = year + month + day;
    const time = hour + minute;

    // Data source flag based on report type
    const reportType = record.temperature_Report_Type || '';
    let dataSourceFlag = '4'; // Default to USAF SURFACE HOURLY

    // Coordinates (scaled by 1000)
    const latitude = formatCoordinate(record.Latitude, 6, true);
    const longitude = formatCoordinate(record.Longitude, 7, false);

    // Report type code
    let reportTypeCode = 'FM-15';
    if (reportType.includes('FM12') || reportType.includes('SYNOP')) {
        reportTypeCode = 'FM-12';
    } else if (reportType.includes('FM16') || reportType.includes('SPECI')) {
        reportTypeCode = 'FM-16';
    } else if (reportType.includes('FM15') || reportType.includes('METAR')) {
        reportTypeCode = 'FM-15';
    }

    // Elevation
    const elevation = formatElevation(record.Elevation);

    // Call letters - only for METAR/SPECI records
    let callLetters = '99999';
    const remarks = record.remarks || '';

    // SYNOP (FM-12) records typically don't have call letters
    if (reportType.includes('FM15') || reportType.includes('FM16') || reportType.includes('METAR') || reportType.includes('SPECI')) {
        // Try to extract call letters from remarks (METAR/SPECI format)
        const icaoMatch = remarks.match(/(?:METAR|SPECI)\s+([A-Z]{4})/);
        if (icaoMatch) {
            callLetters = icaoMatch[1] + ' ';
        } else {
            // Check source station ID fields for ICAO identifier
            const skySourceId = record.sky_cover_1_Source_Station_ID || '';
            if (skySourceId.includes('ICAO-')) {
                callLetters = skySourceId.replace('ICAO-', '').slice(0, 4) + ' ';
            } else {
                // Try to find KDFW or similar in remarks
                const callMatch = remarks.match(/\b([A-Z]{4})\b/);
                if (callMatch && callMatch[1].startsWith('K')) {
                    callLetters = callMatch[1] + ' ';
                }
            }
        }
    }

    // QC process name
    let qcProcess = 'V020';
    if (reportType.includes('FM15') || reportType.includes('FM16')) {
        qcProcess = 'V030';
    }

    // MANDATORY DATA SECTION

    // Wind
    const windDir = formatWindDirection(record.wind_direction, record.wind_direction_Measurement_Code);
    const windDirQuality = mapQualityCode(record.wind_direction_Quality_Code);
    const windTypeCode = getWindTypeCode(record.wind_direction_Measurement_Code, record.wind_speed);
    const windSpeed = formatWindSpeed(record.wind_speed);
    const windSpeedQuality = mapQualityCode(record.wind_speed_Quality_Code);

    // Ceiling
    const ceilingData = formatCeiling(record);

    // Visibility
    const visibility = formatVisibility(record.visibility);
    const visQuality = mapQualityCode(record.visibility_Quality_Code);
    const visVariabilityCode = record.visibility_Measurement_Code;
    const visVariability = (visVariabilityCode && visVariabilityCode.includes('V-Variable')) ? 'V' : 'N';
    // Use '5' for visibility variability quality when visibility is reported
    const visVarQuality = (record.visibility && record.visibility !== '') ? '5' : '9';

    // Temperature
    const temp = formatTemperature(record.temperature);
    const tempQuality = mapQualityCode(record.temperature_Quality_Code);

    // Dew point
    const dewPoint = formatTemperature(record.dew_point_temperature);
    const dewPointQuality = mapQualityCode(record.dew_point_temperature_Quality_Code);

    // Sea level pressure
    const slp = formatPressure(record.sea_level_pressure);
    const slpQuality = mapQualityCode(record.sea_level_pressure_Quality_Code);

    // Build mandatory section (positions 61-105)
    const mandatorySection =
        windDir +                   // 61-63: Wind direction
        windDirQuality +            // 64: Wind direction quality
        windTypeCode +              // 65: Wind type code
        windSpeed +                 // 66-69: Wind speed
        windSpeedQuality +          // 70: Wind speed quality
        ceilingData.height +        // 71-75: Ceiling height
        ceilingData.quality +       // 76: Ceiling quality
        ceilingData.determination + // 77: Ceiling determination
        ceilingData.cavok +         // 78: CAVOK
        visibility +                // 79-84: Visibility
        visQuality +                // 85: Visibility quality
        visVariability +            // 86: Visibility variability
        visVarQuality +             // 87: Visibility variability quality
        temp +                      // 88-92: Temperature
        tempQuality +               // 93: Temperature quality
        dewPoint +                  // 94-98: Dew point
        dewPointQuality +           // 99: Dew point quality
        slp +                       // 100-104: Sea level pressure
        slpQuality;                 // 105: SLP quality

    // ADDITIONAL DATA SECTION
    const additionalData = buildAdditionalDataSection(record);

    // Calculate total variable length
    const variableLength = String(additionalData.length).padStart(4, '0');

    // Build complete record
    const isdLine =
        variableLength +    // 1-4: Variable data length
        usafId +            // 5-10: USAF ID
        wbanId +            // 11-15: WBAN ID
        date +              // 16-23: Date
        time +              // 24-27: Time
        dataSourceFlag +    // 28: Data source flag
        latitude +          // 29-34: Latitude
        longitude +         // 35-41: Longitude
        reportTypeCode +    // 42-46: Report type
        elevation +         // 47-51: Elevation
        callLetters +       // 52-56: Call letters
        qcProcess +         // 57-60: QC process
        mandatorySection +  // 61-105: Mandatory data
        additionalData;     // 106+: Additional data

    return isdLine;
}

/**
 * Format coordinate for ISD (scaled by 1000)
 */
function formatCoordinate(value, length, isLatitude) {
    if (!value || value === '') {
        return isLatitude ? '+99999' : '+999999';
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return isLatitude ? '+99999' : '+999999';
    }

    const scaled = Math.round(num * 1000);
    const sign = scaled >= 0 ? '+' : '-';
    const absValue = Math.abs(scaled);

    if (isLatitude) {
        return sign + String(absValue).padStart(5, '0');
    } else {
        return sign + String(absValue).padStart(6, '0');
    }
}

/**
 * Format elevation for ISD
 */
function formatElevation(value) {
    if (!value || value === '') {
        return '+9999';
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return '+9999';
    }

    const sign = num >= 0 ? '+' : '-';
    const absValue = Math.abs(Math.round(num));
    return sign + String(absValue).padStart(4, '0');
}

/**
 * Format wind direction
 */
function formatWindDirection(value, measurementCode) {
    // Check for calm winds first
    if (measurementCode && measurementCode.includes('C-Calm')) {
        return '999';
    }

    if (!value || value === '' || value === '999') {
        return '999';
    }

    const num = parseInt(value, 10);
    if (isNaN(num) || num < 0 || num > 360) {
        return '999';
    }

    return String(num).padStart(3, '0');
}

/**
 * Get wind type code
 */
function getWindTypeCode(measurementCode, windSpeed) {
    if (measurementCode && measurementCode.includes('C-Calm')) {
        return 'C';
    }
    if (!windSpeed || windSpeed === '' || parseFloat(windSpeed) === 0) {
        return 'C';
    }
    return 'N';
}

/**
 * Format wind speed (scaled by 10, in m/s)
 */
function formatWindSpeed(value) {
    if (!value || value === '') {
        return '9999';
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return '9999';
    }

    const scaled = Math.round(num * 10);
    return String(scaled).padStart(4, '0');
}

/**
 * Format ceiling data
 */
function formatCeiling(record) {
    const skyCover1 = record.sky_cover_1 || '';

    // Default - missing ceiling
    let result = {
        height: '99999',
        quality: '9',
        determination: '9',
        cavok: 'N'
    };

    // Check for clear sky - explicitly clear means no ceiling (unlimited)
    if (skyCover1.includes('CLR') || skyCover1.includes(':00')) {
        result.height = '22000'; // Unlimited ceiling
        result.quality = '5';
        result.determination = '9';
        return result;
    }

    // If no sky cover data at all (typical for SYNOP records), use 99999 (missing)
    if (skyCover1 === '') {
        result.height = '99999';
        result.quality = '9';
        result.determination = '9';
        return result;
    }

    // Find ceiling (BKN, OVC, or VV layer - 5/8 or more coverage)
    const coverFields = [
        { cover: record.sky_cover_1, height: record.sky_cover_baseht_1 },
        { cover: record.sky_cover_2, height: record.sky_cover_baseht_2 },
        { cover: record.sky_cover_3, height: record.sky_cover_baseht_3 }
    ];

    // Ceiling is the lowest BKN, OVC, or VV layer
    let foundCeiling = false;
    for (const field of coverFields) {
        if (field.cover && (field.cover.includes('BKN') || field.cover.includes('OVC') || field.cover.includes('VV'))) {
            if (field.height && field.height !== '') {
                let heightVal = field.height.replace(/^\+/, '');
                heightVal = parseInt(heightVal, 10);
                if (!isNaN(heightVal) && heightVal >= 0) {
                    result.height = String(heightVal).padStart(5, '0');
                    result.quality = '5';
                    result.determination = 'M';
                    foundCeiling = true;
                    break;
                }
            }
        }
    }

    // If we have cloud cover but no ceiling (FEW/SCT only), use 22000 (unlimited)
    if (!foundCeiling) {
        result.height = '22000';
        result.quality = '5';
        result.determination = '9';
    }

    return result;
}

/**
 * Format visibility in meters
 * GHCNh visibility is in kilometers
 */
function formatVisibility(value) {
    if (!value || value === '') {
        return '999999';
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return '999999';
    }

    // Convert km to meters
    const meters = Math.round(num * 1000);
    return String(Math.min(meters, 160000)).padStart(6, '0');
}

/**
 * Format temperature (scaled by 10, in degrees Celsius)
 */
function formatTemperature(value) {
    if (!value || value === '') {
        return '+9999';
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return '+9999';
    }

    const scaled = Math.round(num * 10);
    const sign = scaled >= 0 ? '+' : '-';
    const absValue = Math.abs(scaled);
    return sign + String(absValue).padStart(4, '0');
}

/**
 * Format pressure (scaled by 10, in hPa)
 */
function formatPressure(value) {
    if (!value || value === '') {
        return '99999';
    }

    const num = parseFloat(value);
    if (isNaN(num)) {
        return '99999';
    }

    const scaled = Math.round(num * 10);
    return String(scaled).padStart(5, '0');
}

/**
 * Map GHCNh quality code to ISD quality code
 */
function mapQualityCode(qc) {
    if (!qc || qc === '' || qc === '9' || qc === '9-Missing') {
        return '9';
    }
    const code = String(qc).charAt(0);
    // ISD quality codes:
    // 0 = Passed gross limits check
    // 1 = Passed all QC checks
    // 4 = Passed gross limits, NCEI source
    // 5 = Passed all QC, NCEI source
    // 9 = Passed gross limits if present
    if (code === '1') {
        return '1'; // Passed all QC checks
    }
    if (code === '4') {
        return '4'; // Passed gross limits, NCEI source
    }
    if (code === '5') {
        return '5'; // Passed all QC, NCEI source
    }
    return '1';
}

/**
 * Build additional data section (ADD section)
 */
function buildAdditionalDataSection(record) {
    let addSection = 'ADD';

    // AA1 - Liquid precipitation
    // Format: AA1 + period(2) + depth(4) + condition(1) + quality(1)
    const precip = record.precipitation;
    const precipMeasCode = record.precipitation_Measurement_Code || '';
    if (precip !== undefined && precip !== '') {
        const precipVal = parseFloat(precip);
        if (!isNaN(precipVal)) {
            // GHCNh precipitation is in mm, ISD AA1 scaled by 10
            const precipMm = Math.round(precipVal * 10);
            const precipStr = String(precipMm).padStart(4, '0');
            // Map condition code: 2=Trace, 1=measurement, 9=missing
            let condCode = '9';
            if (precipMeasCode.includes('Trace') || precipMeasCode.includes('2-')) {
                condCode = '2'; // Trace amount
            } else if (precipVal >= 0) {
                condCode = '1'; // Measurement
            }
            const qualCode = '1';
            addSection += 'AA1' + '01' + precipStr + condCode + qualCode;
        }
    }

    // AU1 - Present weather observation (automated) - must come before GA1
    // Format: AU1 + intensity(1) + descriptor(1) + precipitation(2) + obscuration(1) + other(1) + combination(1) + quality(1)
    const auWeather = record.pres_wx_AU1;
    if (auWeather && auWeather !== '') {
        const auCode = mapPresentWeatherAU(auWeather);
        if (auCode) {
            addSection += 'AU1' + auCode;
        }
    }

    // AW1 - Present weather observation (automated WMO code) - must come before GA1
    // Format: AW1 + code(2) + quality(1)
    const awWeather = record.pres_wx_AW1;
    if (awWeather && awWeather !== '') {
        const awCode = extractWeatherCode(awWeather);
        if (awCode) {
            addSection += 'AW1' + awCode.padStart(2, '0') + '5';
        }
    }

    // GA1-GA3 - Sky cover layers
    // Format: GA1 + coverage(2) + quality(1) + height(6,signed) + cloud_type(2) + type_quality(1)
    const skyCoverFields = [
        { cover: record.sky_cover_1, height: record.sky_cover_baseht_1 },
        { cover: record.sky_cover_2, height: record.sky_cover_baseht_2 },
        { cover: record.sky_cover_3, height: record.sky_cover_baseht_3 }
    ];

    // Check if all sky_cover fields are empty
    const allSkyCoverEmpty = skyCoverFields.every(field =>
        (!field.cover || field.cover === '') && (!field.height || field.height === '')
    );

    // If all sky_cover fields are empty, output clear sky (0 oktas)
    // This handles stations that leave sky_cover blank when skies are clear
    if (allSkyCoverEmpty) {
        // Output GA1 with clear sky (0 oktas) when no sky_cover data exists
        addSection += 'GA1' + '00' + '5' + '+99999' + '9' + '999';
    } else {
        // Normal processing of sky cover fields
        skyCoverFields.forEach((field, idx) => {
            // Output GA section if cover OR height exists (SYNOP has height without coverage)
            const hasCover = field.cover && field.cover !== '';
            const hasHeight = field.height && field.height !== '';
            if (hasCover || hasHeight) {
                const gaCode = 'GA' + (idx + 1);
                // Use '99' (missing) for coverage when cover is empty but height exists
                const coverCode = hasCover ? mapSkyCoverCode(field.cover) : '99';
                // Coverage QC: '9' if coverage is missing, '5' if present
                const coverQuality = hasCover ? '5' : '9';
                let heightStr = '+99999';
                // Height QC: '5' if coverage present (NCEI source), '1' if SYNOP-style, '9' if missing
                let heightQuality = '9';
                if (hasHeight) {
                    let h = field.height.replace(/^\+/, '');
                    h = parseInt(h, 10);
                    if (!isNaN(h)) {
                        const sign = h >= 0 ? '+' : '-';
                        heightStr = sign + String(Math.abs(h)).padStart(5, '0');
                        // Use '5' for METAR records (has coverage), '1' for SYNOP (no coverage)
                        heightQuality = hasCover ? '5' : '1';
                    }
                }
                addSection += gaCode + coverCode + coverQuality + heightStr + heightQuality + '999';
            }
        });
    }

    // NOTE: GD (sky cover summation state), GE (sky condition observation), and
    // GF (sky condition summary) sections are NOT output because GHCNh only provides
    // sky_cover data which corresponds to GA (sky cover layer) records. The GD, GE,
    // and GF sections in legacy ISHD files contained derived/supplementary data that
    // is not available in the GHCNh source format.

    // MA1 - Atmospheric pressure observation
    // Format: MA1 + altimeter(5) + altimeter_qc(1) + station_pressure(5) + station_qc(1)
    const stationPressure = record.station_level_pressure;
    const altimeter = record.altimeter;
    if ((stationPressure && stationPressure !== '') || (altimeter && altimeter !== '')) {
        let altStr = '99999';
        let altQc = '9';
        let stpStr = '99999';
        let stpQc = '9';

        if (altimeter && altimeter !== '') {
            const alt = parseFloat(altimeter);
            if (!isNaN(alt)) {
                altStr = String(Math.round(alt * 10)).padStart(5, '0');
                altQc = '5';
            }
        }
        if (stationPressure && stationPressure !== '') {
            const stp = parseFloat(stationPressure);
            if (!isNaN(stp)) {
                stpStr = String(Math.round(stp * 10)).padStart(5, '0');
                stpQc = '5';
            }
        }
        addSection += 'MA1' + altStr + altQc + stpStr + stpQc;
    }

    // MD1 - Atmospheric pressure change
    const pressureChange = record.pressure_3hr_change;
    const pressureChangeMeas = record.pressure_3hr_change_Measurement_Code;
    if (pressureChange && pressureChange !== '') {
        const change = parseFloat(pressureChange);
        if (!isNaN(change)) {
            const tendency = mapPressureTendency(pressureChangeMeas);
            const changeAbs = Math.abs(Math.round(change * 10));
            const changeStr = String(changeAbs).padStart(3, '0');
            addSection += 'MD1' + tendency + '9' + changeStr + '9+9999';
        }
    }

    // OC1 - Wind gust
    const windGust = record.wind_gust;
    if (windGust && windGust !== '') {
        const gust = parseFloat(windGust);
        if (!isNaN(gust) && gust > 0) {
            const gustScaled = Math.round(gust * 10);
            const gustStr = String(gustScaled).padStart(4, '0');
            addSection += 'OC1' + gustStr + '5';
        }
    }

    // MW1 - Present weather observation (manual)
    // Format: MW1 + code(2) + quality(1)
    const mwWeather = record.pres_wx_MW1;
    if (mwWeather && mwWeather !== '') {
        const mwCode = extractWeatherCode(mwWeather);
        if (mwCode) {
            addSection += 'MW1' + mwCode.padStart(2, '0') + '5';
        }
    }

    // REM - Remarks
    const remarks = record.remarks || '';
    if (remarks && remarks !== '') {
        // Clean up remarks and truncate if needed
        const remStr = remarks.slice(0, 500);
        addSection += 'REM' + remStr;
    }

    return addSection;
}

/**
 * Map GHCNh sky cover to ISD coverage code (oktas)
 */
function mapSkyCoverCode(cover) {
    if (!cover) return '99';

    if (cover.includes('CLR') || cover.includes(':00')) return '00';
    if (cover.includes('FEW:01')) return '01';
    if (cover.includes('FEW:02') || cover.includes('FEW')) return '02';
    if (cover.includes('SCT:03')) return '03';
    if (cover.includes('SCT:04') || cover.includes('SCT')) return '04';
    if (cover.includes('BKN:05')) return '05';
    if (cover.includes('BKN:06')) return '06';
    if (cover.includes('BKN:07') || cover.includes('BKN')) return '07';
    if (cover.includes('OVC:08') || cover.includes('OVC')) return '08';
    if (cover.includes('VV')) return '09';

    return '99';
}

/**
 * Map pressure tendency code
 */
function mapPressureTendency(measurementCode) {
    if (!measurementCode) return '9';

    const mc = measurementCode.toLowerCase();
    if (mc.includes('0-incr')) return '0';
    if (mc.includes('1-incr')) return '1';
    if (mc.includes('2-incr')) return '2';
    if (mc.includes('3-decr-or') || mc.includes('3-decr')) return '3';
    if (mc.includes('4-steady')) return '4';
    if (mc.includes('5-decr')) return '5';
    if (mc.includes('6-decr')) return '6';
    if (mc.includes('7-decr')) return '7';
    if (mc.includes('8-steady')) return '8';
    if (mc.includes('none')) return '9';

    return '9';
}

/**
 * Extract numeric weather code from GHCNh present weather string
 * e.g., "SN:71" -> "71", "-SN:03" -> "03"
 */
function extractWeatherCode(weatherStr) {
    if (!weatherStr) return null;
    const match = weatherStr.match(/:(\d+)/);
    return match ? match[1] : null;
}

/**
 * Map GHCNh present weather to AU1 format
 * Format: intensity(1) + descriptor(1) + precipitation(2) + obscuration(1) + other(1) + combination(1) + quality(1)
 */
function mapPresentWeatherAU(weatherStr) {
    if (!weatherStr) return null;

    // Parse the weather string (e.g., "-SN:03", "SN:71")
    let intensity = '0'; // 0=none, 1=light, 2=moderate, 3=heavy
    let descriptor = '0';
    let precipitation = '00';
    let obscuration = '0';
    let other = '0';
    let combination = '1'; // 1=not combined with other elements
    let quality = '5';

    // Check for intensity prefix
    if (weatherStr.startsWith('-')) {
        intensity = '1'; // light
    } else if (weatherStr.startsWith('+')) {
        intensity = '3'; // heavy
    } else {
        intensity = '0'; // moderate/none
    }

    // Map precipitation types
    if (weatherStr.includes('SN')) {
        precipitation = '03'; // Snow
    } else if (weatherStr.includes('RA')) {
        precipitation = '01'; // Rain
    } else if (weatherStr.includes('DZ')) {
        precipitation = '02'; // Drizzle
    } else if (weatherStr.includes('PL') || weatherStr.includes('PE')) {
        precipitation = '04'; // Ice pellets
    } else if (weatherStr.includes('GR') || weatherStr.includes('GS')) {
        precipitation = '05'; // Hail
    }

    // Map obscuration
    if (weatherStr.includes('BR')) {
        obscuration = '1'; // Mist
    } else if (weatherStr.includes('FG')) {
        obscuration = '2'; // Fog
    } else if (weatherStr.includes('HZ')) {
        obscuration = '5'; // Haze
    }

    return intensity + descriptor + precipitation + obscuration + other + combination + quality;
}

/**
 * Check if a record has valid sky_cover data
 * Returns true if sky_cover_1 has a non-empty value
 */
function hasValidSkyCover(record) {
    const skyCover1 = record.sky_cover_1 || '';
    return skyCover1 !== '';
}

/**
 * Get record timestamp in minutes since epoch (simplified for comparison)
 * Returns minutes from year/month/day/hour/minute fields
 */
function getRecordTimestamp(record) {
    const year = parseInt(record.Year, 10) || 0;
    const month = parseInt(record.Month, 10) || 1;
    const day = parseInt(record.Day, 10) || 1;
    const hour = parseInt(record.Hour, 10) || 0;
    const minute = parseInt(record.Minute, 10) || 0;

    // Convert to minutes since a reference point
    // Using a simplified calculation: days * 1440 + hours * 60 + minutes
    // Days calculation: approximate, good enough for 45-minute comparison
    const days = (year * 365) + (month * 30) + day;
    return days * 1440 + hour * 60 + minute;
}

/**
 * Copy sky_cover fields from source record to target record
 */
function copySkyCoverFields(target, source) {
    const skyCoverFields = [
        'sky_cover_1', 'sky_cover_1_Measurement_Code', 'sky_cover_1_Quality_Code',
        'sky_cover_1_Report_Type', 'sky_cover_1_Source_Code', 'sky_cover_1_Source_Station_ID',
        'sky_cover_baseht_1', 'sky_cover_baseht_1_Measurement_Code', 'sky_cover_baseht_1_Quality_Code',
        'sky_cover_baseht_1_Report_Type', 'sky_cover_baseht_1_Source_Code', 'sky_cover_baseht_1_Source_Station_ID',
        'sky_cover_2', 'sky_cover_2_Measurement_Code', 'sky_cover_2_Quality_Code',
        'sky_cover_2_Report_Type', 'sky_cover_2_Source_Code', 'sky_cover_2_Source_Station_ID',
        'sky_cover_baseht_2', 'sky_cover_baseht_2_Measurement_Code', 'sky_cover_baseht_2_Quality_Code',
        'sky_cover_baseht_2_Report_Type', 'sky_cover_baseht_2_Source_Code', 'sky_cover_baseht_2_Source_Station_ID',
        'sky_cover_3', 'sky_cover_3_Measurement_Code', 'sky_cover_3_Quality_Code',
        'sky_cover_3_Report_Type', 'sky_cover_3_Source_Code', 'sky_cover_3_Source_Station_ID',
        'sky_cover_baseht_3', 'sky_cover_baseht_3_Measurement_Code', 'sky_cover_baseht_3_Quality_Code',
        'sky_cover_baseht_3_Report_Type', 'sky_cover_baseht_3_Source_Code', 'sky_cover_baseht_3_Source_Station_ID'
    ];

    for (const field of skyCoverFields) {
        if (source[field] !== undefined && source[field] !== '') {
            target[field] = source[field];
        }
    }
}

/**
 * Fill in missing sky_cover data from previous records within 45 minutes
 * For FM-12 SYNOP records that have blank sky_cover, look back at previous
 * observations to find valid sky_cover data
 */
function fillMissingSkyCover(records) {
    const MAX_LOOKBACK_MINUTES = 45;

    for (let i = 0; i < records.length; i++) {
        const record = records[i];

        // Skip if this record already has valid sky_cover
        if (hasValidSkyCover(record)) {
            continue;
        }

        const currentTimestamp = getRecordTimestamp(record);
        const currentStationId = record.Station_ID;

        // Look backwards through previous records
        for (let j = i - 1; j >= 0; j--) {
            const prevRecord = records[j];

            // Only consider records from the same station
            if (prevRecord.Station_ID !== currentStationId) {
                continue;
            }

            const prevTimestamp = getRecordTimestamp(prevRecord);
            const timeDiff = currentTimestamp - prevTimestamp;

            // Stop if we've gone back more than 45 minutes
            if (timeDiff > MAX_LOOKBACK_MINUTES) {
                break;
            }

            // Skip records with negative time difference (shouldn't happen if sorted)
            if (timeDiff < 0) {
                continue;
            }

            // Found a record within 45 minutes - check if it has valid sky_cover
            if (hasValidSkyCover(prevRecord)) {
                copySkyCoverFields(record, prevRecord);
                break;
            }
        }
    }
}

/**
 * Build station ID mapping from records
 * Scans all records to find USAF-WBAN mappings for each Station_ID
 */
function buildStationIdMap(records) {
    const stationMap = {};

    const stationIdFields = [
        'temperature_Source_Station_ID',
        'wind_direction_Source_Station_ID',
        'wind_speed_Source_Station_ID',
        'sea_level_pressure_Source_Station_ID',
        'station_level_pressure_Source_Station_ID',
        'visibility_Source_Station_ID',
        'dew_point_temperature_Source_Station_ID',
        'altimeter_Source_Station_ID',
        'sky_cover_1_Source_Station_ID'
    ];

    for (const record of records) {
        const ghcnhId = record.Station_ID;
        if (!ghcnhId || stationMap[ghcnhId]) continue;

        // Try each field to find a valid station ID
        for (const field of stationIdFields) {
            const sourceStationId = record[field] || '';
            if (sourceStationId.includes('-') && !sourceStationId.includes('ICAO')) {
                const parts = sourceStationId.split('-');
                if (parts.length === 2 && parts[0].length >= 5 && parts[1].length >= 4) {
                    stationMap[ghcnhId] = {
                        usaf: parts[0].padStart(6, '0').slice(0, 6),
                        wban: parts[1].padStart(5, '0').slice(0, 5)
                    };
                    break;
                }
            }
        }
    }

    return stationMap;
}

/**
 * Convert all records and return ISD output
 */
function convertGHCNhToISD(ghcnhText, progressCallback) {
    const data = parseGHCNh(ghcnhText);
    const outputLines = [];
    let converted = 0;
    let skipped = 0;

    // Build station ID mapping first by scanning all records
    const stationMap = buildStationIdMap(data.records);

    // Fill in missing sky_cover data from previous records within 45 minutes
    // This helps FM-12 SYNOP records which often have blank sky_cover fields
    fillMissingSkyCover(data.records);

    for (let i = 0; i < data.records.length; i++) {
        try {
            const isdLine = convertRecordToISD(data.records[i], stationMap);
            if (isdLine) {
                outputLines.push(isdLine);
                converted++;
            } else {
                skipped++;
            }
        } catch (err) {
            skipped++;
        }

        if (progressCallback && i % 1000 === 0) {
            progressCallback(i, data.records.length);
        }
    }

    return {
        output: outputLines.join('\n'),
        converted: converted,
        skipped: skipped,
        total: data.records.length
    };
}

// Export functions
exports.parseGHCNh = parseGHCNh;
exports.convertRecordToISD = convertRecordToISD;
exports.convertGHCNhToISD = convertGHCNhToISD;
exports.fillMissingSkyCover = fillMissingSkyCover;

})(typeof exports !== 'undefined' ? exports : (window.GHCNhToISD = {}));
