"""
GHCNh to ISD Converter — Python port of ghcnh-to-isd.js

Converts Global Historical Climatology Network hourly (GHCNh) PSV files
to Integrated Surface Data (ISD) fixed-width format for AERMET.
"""


def parse_ghcnh(text):
    """Parse GHCNh pipe-separated values file into list of record dicts."""
    lines = [l for l in text.split('\n') if l.strip()]
    if len(lines) < 2:
        raise ValueError('File appears to be empty or invalid')

    headers = lines[0].split('|')
    records = []
    for line in lines[1:]:
        values = line.split('|')
        record = {}
        for j in range(min(len(headers), len(values))):
            record[headers[j]] = values[j]
        records.append(record)
    return {'headers': headers, 'records': records}


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _fmt_coord(value, length, is_lat):
    missing = '+99999' if is_lat else '+999999'
    if not value or value == '':
        return missing
    try:
        num = float(value)
    except (ValueError, TypeError):
        return missing
    scaled = round(num * 1000)
    sign = '+' if scaled >= 0 else '-'
    pad = 5 if is_lat else 6
    return sign + str(abs(scaled)).zfill(pad)


def _fmt_elevation(value):
    if not value or value == '':
        return '+9999'
    try:
        num = float(value)
    except (ValueError, TypeError):
        return '+9999'
    sign = '+' if num >= 0 else '-'
    return sign + str(abs(round(num))).zfill(4)


def _fmt_wind_dir(value, meas_code):
    if meas_code and 'C-Calm' in meas_code:
        return '999'
    if not value or value == '' or value == '999':
        return '999'
    try:
        num = int(value)
    except (ValueError, TypeError):
        return '999'
    if num < 0 or num > 360:
        return '999'
    return str(num).zfill(3)


def _wind_type_code(meas_code, wind_speed):
    if meas_code and 'C-Calm' in meas_code:
        return 'C'
    if not wind_speed or wind_speed == '':
        return 'C'
    try:
        if float(wind_speed) == 0:
            return 'C'
    except (ValueError, TypeError):
        pass
    return 'N'


def _fmt_wind_speed(value):
    if not value or value == '':
        return '9999'
    try:
        num = float(value)
    except (ValueError, TypeError):
        return '9999'
    return str(round(num * 10)).zfill(4)


def _fmt_ceiling(record):
    sky1 = record.get('sky_cover_1', '')
    result = {'height': '99999', 'quality': '9', 'determination': '9', 'cavok': 'N'}

    if 'CLR' in sky1 or ':00' in sky1:
        result['height'] = '22000'
        result['quality'] = '5'
        result['determination'] = '9'
        return result

    if sky1 == '':
        return result

    cover_fields = [
        {'cover': record.get('sky_cover_1', ''), 'height': record.get('sky_cover_baseht_1', '')},
        {'cover': record.get('sky_cover_2', ''), 'height': record.get('sky_cover_baseht_2', '')},
        {'cover': record.get('sky_cover_3', ''), 'height': record.get('sky_cover_baseht_3', '')},
    ]

    found = False
    for f in cover_fields:
        c = f['cover']
        if c and ('BKN' in c or 'OVC' in c or 'VV' in c):
            h = f['height']
            if h and h != '':
                h = h.lstrip('+')
                try:
                    hv = int(h)
                    if hv >= 0:
                        result['height'] = str(hv).zfill(5)
                        result['quality'] = '5'
                        result['determination'] = 'M'
                        found = True
                        break
                except (ValueError, TypeError):
                    pass

    if not found:
        result['height'] = '22000'
        result['quality'] = '5'
        result['determination'] = '9'
    return result


def _fmt_visibility(value):
    if not value or value == '':
        return '999999'
    try:
        num = float(value)
    except (ValueError, TypeError):
        return '999999'
    meters = round(num * 1000)
    return str(min(meters, 160000)).zfill(6)


def _fmt_temperature(value):
    if not value or value == '':
        return '+9999'
    try:
        num = float(value)
    except (ValueError, TypeError):
        return '+9999'
    scaled = round(num * 10)
    sign = '+' if scaled >= 0 else '-'
    return sign + str(abs(scaled)).zfill(4)


def _fmt_pressure(value):
    if not value or value == '':
        return '99999'
    try:
        num = float(value)
    except (ValueError, TypeError):
        return '99999'
    return str(round(num * 10)).zfill(5)


def _map_quality(qc):
    if not qc or qc == '' or qc == '9' or qc == '9-Missing':
        return '9'
    code = str(qc)[0]
    if code in ('1', '4', '5'):
        return code
    return '1'


# ---------------------------------------------------------------------------
# Sky cover helpers
# ---------------------------------------------------------------------------

def _map_sky_cover_code(cover):
    if not cover:
        return '99'
    for pattern, val in [
        ('CLR', '00'), (':00', '00'),
        ('FEW:01', '01'), ('FEW:02', '02'), ('FEW', '02'),
        ('SCT:03', '03'), ('SCT:04', '04'), ('SCT', '04'),
        ('BKN:05', '05'), ('BKN:06', '06'), ('BKN:07', '07'), ('BKN', '07'),
        ('OVC:08', '08'), ('OVC', '08'),
        ('VV', '09'),
    ]:
        if pattern in cover:
            return val
    return '99'


def _map_pressure_tendency(mc):
    if not mc:
        return '9'
    mc = mc.lower()
    for pattern, val in [
        ('0-incr', '0'), ('1-incr', '1'), ('2-incr', '2'),
        ('3-decr', '3'), ('4-steady', '4'),
        ('5-decr', '5'), ('6-decr', '6'), ('7-decr', '7'),
        ('8-steady', '8'), ('none', '9'),
    ]:
        if pattern in mc:
            return val
    return '9'


def _extract_weather_code(s):
    if not s:
        return None
    import re
    m = re.search(r':(\d+)', s)
    return m.group(1) if m else None


def _map_present_weather_au(s):
    if not s:
        return None
    if s.startswith('-'):
        intensity = '1'
    elif s.startswith('+'):
        intensity = '3'
    else:
        intensity = '0'

    descriptor = '0'
    precip = '00'
    for wx, code in [('SN', '03'), ('RA', '01'), ('DZ', '02'),
                      ('PL', '04'), ('PE', '04'), ('GR', '05'), ('GS', '05')]:
        if wx in s:
            precip = code
            break

    obscuration = '0'
    for wx, code in [('BR', '1'), ('FG', '2'), ('HZ', '5')]:
        if wx in s:
            obscuration = code
            break

    return intensity + descriptor + precip + obscuration + '0' + '1' + '5'


# ---------------------------------------------------------------------------
# Additional data section
# ---------------------------------------------------------------------------

def _build_additional_data(record):
    add = 'ADD'

    # AA1 — precipitation
    precip = record.get('precipitation', '')
    precip_mc = record.get('precipitation_Measurement_Code', '')
    if precip and precip != '':
        try:
            pv = float(precip)
            pmm = round(pv * 10)
            ps = str(pmm).zfill(4)
            if 'Trace' in precip_mc or '2-' in precip_mc:
                cond = '2'
            elif pv >= 0:
                cond = '1'
            else:
                cond = '9'
            add += 'AA1' + '01' + ps + cond + '1'
        except (ValueError, TypeError):
            pass

    # AU1 — present weather (automated)
    au = record.get('pres_wx_AU1', '')
    if au and au != '':
        au_code = _map_present_weather_au(au)
        if au_code:
            add += 'AU1' + au_code

    # AW1 — present weather (WMO code)
    aw = record.get('pres_wx_AW1', '')
    if aw and aw != '':
        aw_code = _extract_weather_code(aw)
        if aw_code:
            add += 'AW1' + aw_code.zfill(2) + '5'

    # GA1-GA3 — sky cover layers
    sc = [
        {'cover': record.get('sky_cover_1', ''), 'height': record.get('sky_cover_baseht_1', '')},
        {'cover': record.get('sky_cover_2', ''), 'height': record.get('sky_cover_baseht_2', '')},
        {'cover': record.get('sky_cover_3', ''), 'height': record.get('sky_cover_baseht_3', '')},
    ]
    all_empty = all(not f['cover'] and not f['height'] for f in sc)

    if all_empty:
        add += 'GA1' + '00' + '5' + '+99999' + '9' + '999'
    else:
        for idx, f in enumerate(sc):
            has_cover = bool(f['cover'])
            has_height = bool(f['height'])
            if has_cover or has_height:
                ga = 'GA' + str(idx + 1)
                cover_code = _map_sky_cover_code(f['cover']) if has_cover else '99'
                cover_q = '5' if has_cover else '9'
                h_str = '+99999'
                h_q = '9'
                if has_height:
                    h = f['height'].lstrip('+')
                    try:
                        hv = int(h)
                        sign = '+' if hv >= 0 else '-'
                        h_str = sign + str(abs(hv)).zfill(5)
                        h_q = '5' if has_cover else '1'
                    except (ValueError, TypeError):
                        pass
                add += ga + cover_code + cover_q + h_str + h_q + '999'

    # MA1 — atmospheric pressure
    stp = record.get('station_level_pressure', '')
    alt = record.get('altimeter', '')
    if stp or alt:
        a_str, a_qc, s_str, s_qc = '99999', '9', '99999', '9'
        if alt:
            try:
                a_str = str(round(float(alt) * 10)).zfill(5)
                a_qc = '5'
            except (ValueError, TypeError):
                pass
        if stp:
            try:
                s_str = str(round(float(stp) * 10)).zfill(5)
                s_qc = '5'
            except (ValueError, TypeError):
                pass
        add += 'MA1' + a_str + a_qc + s_str + s_qc

    # MD1 — pressure change
    pc = record.get('pressure_3hr_change', '')
    pc_mc = record.get('pressure_3hr_change_Measurement_Code', '')
    if pc and pc != '':
        try:
            change = float(pc)
            tendency = _map_pressure_tendency(pc_mc)
            cs = str(abs(round(change * 10))).zfill(3)
            add += 'MD1' + tendency + '9' + cs + '9+9999'
        except (ValueError, TypeError):
            pass

    # OC1 — wind gust
    gust = record.get('wind_gust', '')
    if gust and gust != '':
        try:
            g = float(gust)
            if g > 0:
                add += 'OC1' + str(round(g * 10)).zfill(4) + '5'
        except (ValueError, TypeError):
            pass

    # MW1 — manual weather
    mw = record.get('pres_wx_MW1', '')
    if mw and mw != '':
        mw_code = _extract_weather_code(mw)
        if mw_code:
            add += 'MW1' + mw_code.zfill(2) + '5'

    # REM — remarks
    rem = record.get('remarks', '')
    if rem and rem != '':
        add += 'REM' + rem[:500]

    return add


# ---------------------------------------------------------------------------
# Station ID mapping
# ---------------------------------------------------------------------------

_SOURCE_ID_FIELDS = [
    'temperature_Source_Station_ID',
    'wind_direction_Source_Station_ID',
    'wind_speed_Source_Station_ID',
    'sea_level_pressure_Source_Station_ID',
    'station_level_pressure_Source_Station_ID',
    'visibility_Source_Station_ID',
    'dew_point_temperature_Source_Station_ID',
    'altimeter_Source_Station_ID',
    'sky_cover_1_Source_Station_ID',
]


def build_station_id_map(records):
    """Scan records to build Station_ID -> {usaf, wban} mapping."""
    smap = {}
    for rec in records:
        gid = rec.get('Station_ID', '')
        if not gid or gid in smap:
            continue
        for field in _SOURCE_ID_FIELDS:
            ssid = rec.get(field, '')
            if '-' in ssid and 'ICAO' not in ssid:
                parts = ssid.split('-')
                if len(parts) == 2 and len(parts[0]) >= 5 and len(parts[1]) >= 4:
                    smap[gid] = {
                        'usaf': parts[0].zfill(6)[:6],
                        'wban': parts[1].zfill(5)[:5],
                    }
                    break
    return smap


# ---------------------------------------------------------------------------
# Sky cover fill
# ---------------------------------------------------------------------------

_SKY_COVER_FIELDS = [
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
    'sky_cover_baseht_3_Report_Type', 'sky_cover_baseht_3_Source_Code', 'sky_cover_baseht_3_Source_Station_ID',
]


def _record_timestamp(rec):
    y = int(rec.get('Year', 0) or 0)
    mo = int(rec.get('Month', 1) or 1)
    d = int(rec.get('Day', 1) or 1)
    h = int(rec.get('Hour', 0) or 0)
    mi = int(rec.get('Minute', 0) or 0)
    days = y * 365 + mo * 30 + d
    return days * 1440 + h * 60 + mi


def fill_missing_sky_cover(records):
    """Fill blank sky_cover from prior record within 45 minutes."""
    for i, rec in enumerate(records):
        if rec.get('sky_cover_1', ''):
            continue
        ts = _record_timestamp(rec)
        sid = rec.get('Station_ID', '')
        for j in range(i - 1, -1, -1):
            prev = records[j]
            if prev.get('Station_ID', '') != sid:
                continue
            diff = ts - _record_timestamp(prev)
            if diff > 45:
                break
            if diff < 0:
                continue
            if prev.get('sky_cover_1', ''):
                for f in _SKY_COVER_FIELDS:
                    v = prev.get(f, '')
                    if v:
                        rec[f] = v
                break


# ---------------------------------------------------------------------------
# Single record conversion
# ---------------------------------------------------------------------------

def convert_record_to_isd(record, station_map):
    """Convert one GHCNh record dict to an ISD fixed-width line."""
    import re

    usaf = '999999'
    wban = '99999'
    gid = record.get('Station_ID', '')
    if station_map and gid in station_map:
        usaf = station_map[gid]['usaf']
        wban = station_map[gid]['wban']
    else:
        for field in _SOURCE_ID_FIELDS:
            ssid = record.get(field, '')
            if '-' in ssid and 'ICAO' not in ssid:
                parts = ssid.split('-')
                if len(parts) == 2 and len(parts[0]) >= 5 and len(parts[1]) >= 4:
                    usaf = parts[0].zfill(6)[:6]
                    wban = parts[1].zfill(5)[:5]
                    break
        if usaf == '999999' and gid and gid.startswith('USW') and len(gid) >= 11:
            wban = gid[6:11]

    year = str(record.get('Year', '9999')).zfill(4)
    month = str(record.get('Month', '99')).zfill(2)
    day = str(record.get('Day', '99')).zfill(2)
    hour = str(record.get('Hour', '99')).zfill(2)
    minute = str(record.get('Minute', '99')).zfill(2)
    date = year + month + day
    time_ = hour + minute

    report_type = record.get('temperature_Report_Type', '')
    data_source_flag = '4'

    latitude = _fmt_coord(record.get('Latitude'), 6, True)
    longitude = _fmt_coord(record.get('Longitude'), 7, False)

    rtype = 'FM-15'
    if 'FM12' in report_type or 'SYNOP' in report_type:
        rtype = 'FM-12'
    elif 'FM16' in report_type or 'SPECI' in report_type:
        rtype = 'FM-16'

    elevation = _fmt_elevation(record.get('Elevation'))

    call = '99999'
    remarks = record.get('remarks', '')
    if 'FM15' in report_type or 'FM16' in report_type or 'METAR' in report_type or 'SPECI' in report_type:
        m = re.search(r'(?:METAR|SPECI)\s+([A-Z]{4})', remarks) if remarks else None
        if m:
            call = m.group(1) + ' '
        else:
            sky_src = record.get('sky_cover_1_Source_Station_ID', '')
            if 'ICAO-' in sky_src:
                call = sky_src.replace('ICAO-', '')[:4] + ' '
            else:
                cm = re.search(r'\b([A-Z]{4})\b', remarks) if remarks else None
                if cm and cm.group(1).startswith('K'):
                    call = cm.group(1) + ' '

    qc_proc = 'V030' if ('FM15' in report_type or 'FM16' in report_type) else 'V020'

    wind_dir = _fmt_wind_dir(record.get('wind_direction'), record.get('wind_direction_Measurement_Code'))
    wind_dir_q = _map_quality(record.get('wind_direction_Quality_Code'))
    wind_type = _wind_type_code(record.get('wind_direction_Measurement_Code'), record.get('wind_speed'))
    wind_spd = _fmt_wind_speed(record.get('wind_speed'))
    wind_spd_q = _map_quality(record.get('wind_speed_Quality_Code'))

    ceil = _fmt_ceiling(record)

    vis = _fmt_visibility(record.get('visibility'))
    vis_q = _map_quality(record.get('visibility_Quality_Code'))
    vis_mc = record.get('visibility_Measurement_Code', '')
    vis_var = 'V' if vis_mc and 'V-Variable' in vis_mc else 'N'
    vis_var_q = '5' if record.get('visibility') else '9'

    temp = _fmt_temperature(record.get('temperature'))
    temp_q = _map_quality(record.get('temperature_Quality_Code'))
    dew = _fmt_temperature(record.get('dew_point_temperature'))
    dew_q = _map_quality(record.get('dew_point_temperature_Quality_Code'))
    slp = _fmt_pressure(record.get('sea_level_pressure'))
    slp_q = _map_quality(record.get('sea_level_pressure_Quality_Code'))

    mandatory = (wind_dir + wind_dir_q + wind_type + wind_spd + wind_spd_q +
                 ceil['height'] + ceil['quality'] + ceil['determination'] + ceil['cavok'] +
                 vis + vis_q + vis_var + vis_var_q +
                 temp + temp_q + dew + dew_q + slp + slp_q)

    additional = _build_additional_data(record)
    var_len = str(len(additional)).zfill(4)

    return (var_len + usaf + wban + date + time_ + data_source_flag +
            latitude + longitude + rtype + elevation + call + qc_proc +
            mandatory + additional)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def convert_ghcnh_to_isd(text, progress_cb=None):
    """Convert GHCNh PSV text to ISD format. Returns dict with output, stats."""
    data = parse_ghcnh(text)
    station_map = build_station_id_map(data['records'])
    fill_missing_sky_cover(data['records'])

    lines = []
    converted = 0
    skipped = 0
    for i, rec in enumerate(data['records']):
        try:
            line = convert_record_to_isd(rec, station_map)
            if line:
                lines.append(line)
                converted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
        if progress_cb and i % 1000 == 0:
            progress_cb(i, len(data['records']))

    return {
        'output': '\n'.join(lines),
        'converted': converted,
        'skipped': skipped,
        'total': len(data['records']),
    }


def convert_ghcnh_file(input_path, output_path, progress_cb=None):
    """Convenience: read GHCNh file, write ISD file."""
    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    result = convert_ghcnh_to_isd(text, progress_cb)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result['output'])
    return result
