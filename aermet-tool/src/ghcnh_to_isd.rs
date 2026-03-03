/// GHCNh to ISD Converter — converts GHCNh PSV files to ISD fixed-width format for AERMET.
use regex::Regex;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

// ---------------------------------------------------------------------------
// PSV parsing
// ---------------------------------------------------------------------------

struct GhcnhData {
    #[allow(dead_code)]
    headers: Vec<String>,
    records: Vec<HashMap<String, String>>,
}

fn parse_ghcnh(text: &str) -> Result<GhcnhData, String> {
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    if lines.len() < 2 {
        return Err("File appears to be empty or invalid".to_string());
    }

    let headers: Vec<String> = lines[0].split('|').map(|s| s.to_string()).collect();
    let mut records = Vec::new();

    for line in &lines[1..] {
        let values: Vec<&str> = line.split('|').collect();
        let mut record = HashMap::new();
        for (j, header) in headers.iter().enumerate() {
            if j < values.len() {
                record.insert(header.clone(), values[j].to_string());
            }
        }
        records.push(record);
    }

    Ok(GhcnhData { headers, records })
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

fn get(rec: &HashMap<String, String>, key: &str) -> String {
    rec.get(key).cloned().unwrap_or_default()
}

fn fmt_coord(value: &str, is_lat: bool) -> String {
    let missing = if is_lat { "+99999" } else { "+999999" };
    if value.is_empty() {
        return missing.to_string();
    }
    match value.parse::<f64>() {
        Ok(num) => {
            let scaled = (num * 1000.0).round() as i64;
            let sign = if scaled >= 0 { '+' } else { '-' };
            let pad = if is_lat { 5 } else { 6 };
            format!("{}{:0>width$}", sign, scaled.unsigned_abs(), width = pad)
        }
        Err(_) => missing.to_string(),
    }
}

fn fmt_elevation(value: &str) -> String {
    if value.is_empty() {
        return "+9999".to_string();
    }
    match value.parse::<f64>() {
        Ok(num) => {
            let sign = if num >= 0.0 { '+' } else { '-' };
            format!("{}{:04}", sign, num.abs().round() as u64)
        }
        Err(_) => "+9999".to_string(),
    }
}

fn fmt_wind_dir(value: &str, meas_code: &str) -> String {
    if meas_code.contains("C-Calm") {
        return "999".to_string();
    }
    if value.is_empty() || value == "999" {
        return "999".to_string();
    }
    match value.parse::<i32>() {
        Ok(num) if (0..=360).contains(&num) => format!("{:03}", num),
        _ => "999".to_string(),
    }
}

fn wind_type_code(meas_code: &str, wind_speed: &str) -> char {
    if meas_code.contains("C-Calm") {
        return 'C';
    }
    if wind_speed.is_empty() {
        return 'C';
    }
    if let Ok(v) = wind_speed.parse::<f64>() {
        if v == 0.0 {
            return 'C';
        }
    }
    'N'
}

fn fmt_wind_speed(value: &str) -> String {
    if value.is_empty() {
        return "9999".to_string();
    }
    match value.parse::<f64>() {
        Ok(num) => format!("{:04}", (num * 10.0).round() as u64),
        Err(_) => "9999".to_string(),
    }
}

fn fmt_ceiling(record: &HashMap<String, String>) -> (String, char, char, char) {
    // Returns (height, quality, determination, cavok)
    let sky1 = get(record, "sky_cover_1");

    if sky1.contains("CLR") || sky1.contains(":00") {
        return ("22000".to_string(), '5', '9', 'N');
    }

    if sky1.is_empty() {
        return ("99999".to_string(), '9', '9', 'N');
    }

    let cover_fields = [
        (get(record, "sky_cover_1"), get(record, "sky_cover_baseht_1")),
        (get(record, "sky_cover_2"), get(record, "sky_cover_baseht_2")),
        (get(record, "sky_cover_3"), get(record, "sky_cover_baseht_3")),
    ];

    for (cover, height) in &cover_fields {
        if cover.contains("BKN") || cover.contains("OVC") || cover.contains("VV") {
            if !height.is_empty() {
                let h = height.trim_start_matches('+');
                if let Ok(hv) = h.parse::<i64>() {
                    if hv >= 0 {
                        return (format!("{:05}", hv), '5', 'M', 'N');
                    }
                }
            }
        }
    }

    ("22000".to_string(), '5', '9', 'N')
}

fn fmt_visibility(value: &str) -> String {
    if value.is_empty() {
        return "999999".to_string();
    }
    match value.parse::<f64>() {
        Ok(num) => {
            let meters = (num * 1000.0).round() as u64;
            format!("{:06}", meters.min(160000))
        }
        Err(_) => "999999".to_string(),
    }
}

fn fmt_temperature(value: &str) -> String {
    if value.is_empty() {
        return "+9999".to_string();
    }
    match value.parse::<f64>() {
        Ok(num) => {
            let scaled = (num * 10.0).round() as i64;
            let sign = if scaled >= 0 { '+' } else { '-' };
            format!("{}{:04}", sign, scaled.unsigned_abs())
        }
        Err(_) => "+9999".to_string(),
    }
}

fn fmt_pressure(value: &str) -> String {
    if value.is_empty() {
        return "99999".to_string();
    }
    match value.parse::<f64>() {
        Ok(num) => format!("{:05}", (num * 10.0).round() as u64),
        Err(_) => "99999".to_string(),
    }
}

fn map_quality(qc: &str) -> char {
    if qc.is_empty() || qc == "9" || qc.starts_with("9-") {
        return '9';
    }
    let code = qc.chars().next().unwrap_or('9');
    if code == '1' || code == '4' || code == '5' {
        code
    } else {
        '1'
    }
}

fn map_sky_cover_code(cover: &str) -> &str {
    if cover.is_empty() {
        return "99";
    }
    let patterns: &[(&str, &str)] = &[
        ("CLR", "00"),
        (":00", "00"),
        ("FEW:01", "01"),
        ("FEW:02", "02"),
        ("FEW", "02"),
        ("SCT:03", "03"),
        ("SCT:04", "04"),
        ("SCT", "04"),
        ("BKN:05", "05"),
        ("BKN:06", "06"),
        ("BKN:07", "07"),
        ("BKN", "07"),
        ("OVC:08", "08"),
        ("OVC", "08"),
        ("VV", "09"),
    ];
    for (pat, val) in patterns {
        if cover.contains(pat) {
            return val;
        }
    }
    "99"
}

fn map_pressure_tendency(mc: &str) -> char {
    if mc.is_empty() {
        return '9';
    }
    let mc = mc.to_lowercase();
    let patterns: &[(&str, char)] = &[
        ("0-incr", '0'),
        ("1-incr", '1'),
        ("2-incr", '2'),
        ("3-decr", '3'),
        ("4-steady", '4'),
        ("5-decr", '5'),
        ("6-decr", '6'),
        ("7-decr", '7'),
        ("8-steady", '8'),
        ("none", '9'),
    ];
    for (pat, val) in patterns {
        if mc.contains(pat) {
            return *val;
        }
    }
    '9'
}

fn extract_weather_code(s: &str) -> Option<String> {
    if s.is_empty() {
        return None;
    }
    let re = Regex::new(r":(\d+)").unwrap();
    re.captures(s).map(|c| c[1].to_string())
}

fn map_present_weather_au(s: &str) -> Option<String> {
    if s.is_empty() {
        return None;
    }
    let intensity = if s.starts_with('-') {
        '1'
    } else if s.starts_with('+') {
        '3'
    } else {
        '0'
    };

    let descriptor = '0';
    let mut precip = "00";
    for (wx, code) in &[
        ("SN", "03"),
        ("RA", "01"),
        ("DZ", "02"),
        ("PL", "04"),
        ("PE", "04"),
        ("GR", "05"),
        ("GS", "05"),
    ] {
        if s.contains(wx) {
            precip = code;
            break;
        }
    }

    let mut obscuration = '0';
    for (wx, code) in &[("BR", '1'), ("FG", '2'), ("HZ", '5')] {
        if s.contains(wx) {
            obscuration = *code;
            break;
        }
    }

    Some(format!("{intensity}{descriptor}{precip}{obscuration}015"))
}

// ---------------------------------------------------------------------------
// Additional data section
// ---------------------------------------------------------------------------

fn build_additional_data(record: &HashMap<String, String>) -> String {
    let mut add = "ADD".to_string();

    // AA1 — precipitation
    let precip = get(record, "precipitation");
    let precip_mc = get(record, "precipitation_Measurement_Code");
    if !precip.is_empty() {
        if let Ok(pv) = precip.parse::<f64>() {
            let pmm = (pv * 10.0).round() as i64;
            let ps = format!("{:04}", pmm);
            let cond = if precip_mc.contains("Trace") || precip_mc.contains("2-") {
                '2'
            } else if pv >= 0.0 {
                '1'
            } else {
                '9'
            };
            add.push_str(&format!("AA101{ps}{cond}1"));
        }
    }

    // AU1 — present weather (automated)
    let au = get(record, "pres_wx_AU1");
    if !au.is_empty() {
        if let Some(au_code) = map_present_weather_au(&au) {
            add.push_str(&format!("AU1{au_code}"));
        }
    }

    // AW1 — present weather (WMO code)
    let aw = get(record, "pres_wx_AW1");
    if !aw.is_empty() {
        if let Some(aw_code) = extract_weather_code(&aw) {
            add.push_str(&format!("AW1{:0>2}5", aw_code));
        }
    }

    // GA1-GA3 — sky cover layers
    let sc = [
        (get(record, "sky_cover_1"), get(record, "sky_cover_baseht_1")),
        (get(record, "sky_cover_2"), get(record, "sky_cover_baseht_2")),
        (get(record, "sky_cover_3"), get(record, "sky_cover_baseht_3")),
    ];
    let all_empty = sc.iter().all(|(c, h)| c.is_empty() && h.is_empty());

    if all_empty {
        add.push_str("GA100 5+999999999");
    } else {
        for (idx, (cover, height)) in sc.iter().enumerate() {
            if !cover.is_empty() || !height.is_empty() {
                let ga = format!("GA{}", idx + 1);
                let cover_code = if !cover.is_empty() {
                    map_sky_cover_code(cover)
                } else {
                    "99"
                };
                let cover_q = if !cover.is_empty() { '5' } else { '9' };
                let (h_str, h_q) = if !height.is_empty() {
                    let h = height.trim_start_matches('+');
                    match h.parse::<i64>() {
                        Ok(hv) => {
                            let sign = if hv >= 0 { '+' } else { '-' };
                            let hq = if !cover.is_empty() { '5' } else { '1' };
                            (format!("{}{:05}", sign, hv.unsigned_abs()), hq)
                        }
                        Err(_) => ("+99999".to_string(), '9'),
                    }
                } else {
                    ("+99999".to_string(), '9')
                };
                add.push_str(&format!("{ga}{cover_code}{cover_q}{h_str}{h_q}999"));
            }
        }
    }

    // MA1 — atmospheric pressure
    let stp = get(record, "station_level_pressure");
    let alt = get(record, "altimeter");
    if !stp.is_empty() || !alt.is_empty() {
        let (a_str, a_qc) = if !alt.is_empty() {
            match alt.parse::<f64>() {
                Ok(v) => (format!("{:05}", (v * 10.0).round() as u64), '5'),
                Err(_) => ("99999".to_string(), '9'),
            }
        } else {
            ("99999".to_string(), '9')
        };
        let (s_str, s_qc) = if !stp.is_empty() {
            match stp.parse::<f64>() {
                Ok(v) => (format!("{:05}", (v * 10.0).round() as u64), '5'),
                Err(_) => ("99999".to_string(), '9'),
            }
        } else {
            ("99999".to_string(), '9')
        };
        add.push_str(&format!("MA1{a_str}{a_qc}{s_str}{s_qc}"));
    }

    // MD1 — pressure change
    let pc = get(record, "pressure_3hr_change");
    let pc_mc = get(record, "pressure_3hr_change_Measurement_Code");
    if !pc.is_empty() {
        if let Ok(change) = pc.parse::<f64>() {
            let tendency = map_pressure_tendency(&pc_mc);
            let cs = format!("{:03}", (change.abs() * 10.0).round() as u64);
            add.push_str(&format!("MD1{tendency}9{cs}9+9999"));
        }
    }

    // OC1 — wind gust
    let gust = get(record, "wind_gust");
    if !gust.is_empty() {
        if let Ok(g) = gust.parse::<f64>() {
            if g > 0.0 {
                add.push_str(&format!("OC1{:04}5", (g * 10.0).round() as u64));
            }
        }
    }

    // MW1 — manual weather
    let mw = get(record, "pres_wx_MW1");
    if !mw.is_empty() {
        if let Some(mw_code) = extract_weather_code(&mw) {
            add.push_str(&format!("MW1{:0>2}5", mw_code));
        }
    }

    // REM — remarks
    let rem = get(record, "remarks");
    if !rem.is_empty() {
        let truncated = if rem.len() > 500 { &rem[..500] } else { &rem };
        add.push_str(&format!("REM{truncated}"));
    }

    add
}

// ---------------------------------------------------------------------------
// Station ID mapping
// ---------------------------------------------------------------------------

const SOURCE_ID_FIELDS: &[&str] = &[
    "temperature_Source_Station_ID",
    "wind_direction_Source_Station_ID",
    "wind_speed_Source_Station_ID",
    "sea_level_pressure_Source_Station_ID",
    "station_level_pressure_Source_Station_ID",
    "visibility_Source_Station_ID",
    "dew_point_temperature_Source_Station_ID",
    "altimeter_Source_Station_ID",
    "sky_cover_1_Source_Station_ID",
];

fn build_station_id_map(records: &[HashMap<String, String>]) -> HashMap<String, (String, String)> {
    let mut smap = HashMap::new();
    for rec in records {
        let gid = get(rec, "Station_ID");
        if gid.is_empty() || smap.contains_key(&gid) {
            continue;
        }
        for field in SOURCE_ID_FIELDS {
            let ssid = get(rec, field);
            if ssid.contains('-') && !ssid.contains("ICAO") {
                let parts: Vec<&str> = ssid.split('-').collect();
                if parts.len() == 2 && parts[0].len() >= 5 && parts[1].len() >= 4 {
                    let usaf = format!("{:0>6}", &parts[0][..parts[0].len().min(6)]);
                    let wban = format!("{:0>5}", &parts[1][..parts[1].len().min(5)]);
                    smap.insert(gid.clone(), (usaf, wban));
                    break;
                }
            }
        }
    }
    smap
}

// ---------------------------------------------------------------------------
// Sky cover fill
// ---------------------------------------------------------------------------

const SKY_COVER_FIELDS: &[&str] = &[
    "sky_cover_1", "sky_cover_1_Measurement_Code", "sky_cover_1_Quality_Code",
    "sky_cover_1_Report_Type", "sky_cover_1_Source_Code", "sky_cover_1_Source_Station_ID",
    "sky_cover_baseht_1", "sky_cover_baseht_1_Measurement_Code", "sky_cover_baseht_1_Quality_Code",
    "sky_cover_baseht_1_Report_Type", "sky_cover_baseht_1_Source_Code", "sky_cover_baseht_1_Source_Station_ID",
    "sky_cover_2", "sky_cover_2_Measurement_Code", "sky_cover_2_Quality_Code",
    "sky_cover_2_Report_Type", "sky_cover_2_Source_Code", "sky_cover_2_Source_Station_ID",
    "sky_cover_baseht_2", "sky_cover_baseht_2_Measurement_Code", "sky_cover_baseht_2_Quality_Code",
    "sky_cover_baseht_2_Report_Type", "sky_cover_baseht_2_Source_Code", "sky_cover_baseht_2_Source_Station_ID",
    "sky_cover_3", "sky_cover_3_Measurement_Code", "sky_cover_3_Quality_Code",
    "sky_cover_3_Report_Type", "sky_cover_3_Source_Code", "sky_cover_3_Source_Station_ID",
    "sky_cover_baseht_3", "sky_cover_baseht_3_Measurement_Code", "sky_cover_baseht_3_Quality_Code",
    "sky_cover_baseht_3_Report_Type", "sky_cover_baseht_3_Source_Code", "sky_cover_baseht_3_Source_Station_ID",
];

fn record_timestamp(rec: &HashMap<String, String>) -> i64 {
    let y: i64 = get(rec, "Year").parse().unwrap_or(0);
    let mo: i64 = get(rec, "Month").parse().unwrap_or(1);
    let d: i64 = get(rec, "Day").parse().unwrap_or(1);
    let h: i64 = get(rec, "Hour").parse().unwrap_or(0);
    let mi: i64 = get(rec, "Minute").parse().unwrap_or(0);
    (y * 365 + mo * 30 + d) * 1440 + h * 60 + mi
}

fn fill_missing_sky_cover(records: &mut [HashMap<String, String>]) {
    // We need to iterate and look back, so we collect timestamps first
    let timestamps: Vec<i64> = records.iter().map(record_timestamp).collect();
    let station_ids: Vec<String> = records.iter().map(|r| get(r, "Station_ID")).collect();

    for i in 0..records.len() {
        if !get(&records[i], "sky_cover_1").is_empty() {
            continue;
        }
        let ts = timestamps[i];
        let sid = &station_ids[i];

        for j in (0..i).rev() {
            if &station_ids[j] != sid {
                continue;
            }
            let diff = ts - timestamps[j];
            if diff > 45 {
                break;
            }
            if diff < 0 {
                continue;
            }
            if !get(&records[j], "sky_cover_1").is_empty() {
                // Clone values from prior record
                let vals: Vec<(String, String)> = SKY_COVER_FIELDS
                    .iter()
                    .filter_map(|f| {
                        let v = get(&records[j], f);
                        if !v.is_empty() {
                            Some((f.to_string(), v))
                        } else {
                            None
                        }
                    })
                    .collect();
                for (k, v) in vals {
                    records[i].insert(k, v);
                }
                break;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Single record conversion
// ---------------------------------------------------------------------------

fn convert_record_to_isd(
    record: &HashMap<String, String>,
    station_map: &HashMap<String, (String, String)>,
) -> Option<String> {
    let gid = get(record, "Station_ID");
    let (mut usaf, mut wban) = ("999999".to_string(), "99999".to_string());

    if let Some((u, w)) = station_map.get(&gid) {
        usaf = u.clone();
        wban = w.clone();
    } else {
        // Try inline extraction
        for field in SOURCE_ID_FIELDS {
            let ssid = get(record, field);
            if ssid.contains('-') && !ssid.contains("ICAO") {
                let parts: Vec<&str> = ssid.split('-').collect();
                if parts.len() == 2 && parts[0].len() >= 5 && parts[1].len() >= 4 {
                    usaf = format!("{:0>6}", &parts[0][..parts[0].len().min(6)]);
                    wban = format!("{:0>5}", &parts[1][..parts[1].len().min(5)]);
                    break;
                }
            }
        }
        if usaf == "999999" && gid.starts_with("USW") && gid.len() >= 11 {
            wban = gid[6..11].to_string();
        }
    }

    let year = format!("{:04}", get(record, "Year").parse::<i32>().unwrap_or(9999));
    let month = format!("{:02}", get(record, "Month").parse::<i32>().unwrap_or(99));
    let day = format!("{:02}", get(record, "Day").parse::<i32>().unwrap_or(99));
    let hour = format!("{:02}", get(record, "Hour").parse::<i32>().unwrap_or(99));
    let minute = format!("{:02}", get(record, "Minute").parse::<i32>().unwrap_or(99));
    let date = format!("{year}{month}{day}");
    let time = format!("{hour}{minute}");

    let report_type = get(record, "temperature_Report_Type");
    let data_source_flag = "4";

    let latitude = fmt_coord(&get(record, "Latitude"), true);
    let longitude = fmt_coord(&get(record, "Longitude"), false);

    let rtype = if report_type.contains("FM12") || report_type.contains("SYNOP") {
        "FM-12"
    } else if report_type.contains("FM16") || report_type.contains("SPECI") {
        "FM-16"
    } else {
        "FM-15"
    };

    let elevation = fmt_elevation(&get(record, "Elevation"));

    let mut call = "99999".to_string();
    let remarks = get(record, "remarks");
    if report_type.contains("FM15")
        || report_type.contains("FM16")
        || report_type.contains("METAR")
        || report_type.contains("SPECI")
    {
        let re_metar = Regex::new(r"(?:METAR|SPECI)\s+([A-Z]{4})").unwrap();
        if let Some(cap) = re_metar.captures(&remarks) {
            call = format!("{} ", &cap[1]);
        } else {
            let sky_src = get(record, "sky_cover_1_Source_Station_ID");
            if sky_src.contains("ICAO-") {
                let icao = sky_src.replace("ICAO-", "");
                call = format!("{} ", &icao[..icao.len().min(4)]);
            } else {
                let re_icao = Regex::new(r"\b([A-Z]{4})\b").unwrap();
                if let Some(cap) = re_icao.captures(&remarks) {
                    if cap[1].starts_with('K') {
                        call = format!("{} ", &cap[1]);
                    }
                }
            }
        }
    }

    let qc_proc = if report_type.contains("FM15") || report_type.contains("FM16") {
        "V030"
    } else {
        "V020"
    };

    let wind_dir = fmt_wind_dir(
        &get(record, "wind_direction"),
        &get(record, "wind_direction_Measurement_Code"),
    );
    let wind_dir_q = map_quality(&get(record, "wind_direction_Quality_Code"));
    let wind_type = wind_type_code(
        &get(record, "wind_direction_Measurement_Code"),
        &get(record, "wind_speed"),
    );
    let wind_spd = fmt_wind_speed(&get(record, "wind_speed"));
    let wind_spd_q = map_quality(&get(record, "wind_speed_Quality_Code"));

    let (ceil_h, ceil_q, ceil_d, ceil_c) = fmt_ceiling(record);

    let vis = fmt_visibility(&get(record, "visibility"));
    let vis_q = map_quality(&get(record, "visibility_Quality_Code"));
    let vis_mc = get(record, "visibility_Measurement_Code");
    let vis_var = if vis_mc.contains("V-Variable") { 'V' } else { 'N' };
    let vis_var_q = if !get(record, "visibility").is_empty() { '5' } else { '9' };

    let temp = fmt_temperature(&get(record, "temperature"));
    let temp_q = map_quality(&get(record, "temperature_Quality_Code"));
    let dew = fmt_temperature(&get(record, "dew_point_temperature"));
    let dew_q = map_quality(&get(record, "dew_point_temperature_Quality_Code"));
    let slp = fmt_pressure(&get(record, "sea_level_pressure"));
    let slp_q = map_quality(&get(record, "sea_level_pressure_Quality_Code"));

    let mandatory = format!(
        "{wind_dir}{wind_dir_q}{wind_type}{wind_spd}{wind_spd_q}\
         {ceil_h}{ceil_q}{ceil_d}{ceil_c}\
         {vis}{vis_q}{vis_var}{vis_var_q}\
         {temp}{temp_q}{dew}{dew_q}{slp}{slp_q}"
    );

    let additional = build_additional_data(record);
    let var_len = format!("{:04}", additional.len());

    Some(format!(
        "{var_len}{usaf}{wban}{date}{time}{data_source_flag}\
         {latitude}{longitude}{rtype}{elevation}{call}{qc_proc}\
         {mandatory}{additional}"
    ))
}

// ---------------------------------------------------------------------------
// Main entry points
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, serde::Serialize)]
pub struct ConversionStats {
    pub converted: usize,
    pub skipped: usize,
    pub total: usize,
}

pub fn convert_ghcnh_to_isd(
    text: &str,
    progress_cb: Option<&dyn Fn(usize, usize)>,
) -> Result<(String, ConversionStats), String> {
    let mut data = parse_ghcnh(text)?;
    let station_map = build_station_id_map(&data.records);
    fill_missing_sky_cover(&mut data.records);

    let mut lines = Vec::new();
    let mut converted = 0usize;
    let mut skipped = 0usize;
    let total = data.records.len();

    for (i, rec) in data.records.iter().enumerate() {
        match convert_record_to_isd(rec, &station_map) {
            Some(line) => {
                lines.push(line);
                converted += 1;
            }
            None => skipped += 1,
        }
        if let Some(cb) = progress_cb {
            if i % 1000 == 0 {
                cb(i, total);
            }
        }
    }

    Ok((
        lines.join("\n"),
        ConversionStats {
            converted,
            skipped,
            total,
        },
    ))
}

pub fn convert_ghcnh_file(
    input_path: &Path,
    output_path: &Path,
    progress_cb: Option<&dyn Fn(usize, usize)>,
) -> Result<ConversionStats, String> {
    let text = fs::read_to_string(input_path).map_err(|e| format!("Read error: {e}"))?;
    let (output, stats) = convert_ghcnh_to_isd(&text, progress_cb)?;
    fs::write(output_path, output).map_err(|e| format!("Write error: {e}"))?;
    Ok(stats)
}
