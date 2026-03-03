/// IGRA (Integrated Global Radiosonde Archive) utilities.
///
/// Downloads, parses, and trims upper air sounding data.
use crate::http_client::client;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;

const IGRA_DATA_URL: &str =
    "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/data-por";
pub const IGRA_STATION_LIST_URL: &str =
    "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/doc/igra2-station-list.txt";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IgraStation {
    pub id: String,
    pub lat: f64,
    pub lon: f64,
    pub elev: f64,
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub name: String,
    pub first_year: i32,
    pub last_year: i32,
}

/// Parse the IGRA station list (fixed-width format).
pub fn parse_igra_station_list(text: &str) -> Vec<IgraStation> {
    let mut stations = Vec::new();
    for line in text.lines() {
        if line.trim().len() < 80 {
            continue;
        }
        let sid = line.get(0..11).unwrap_or("").trim().to_string();
        let lat = line.get(12..20).and_then(|s| s.trim().parse::<f64>().ok());
        let lon = line.get(21..30).and_then(|s| s.trim().parse::<f64>().ok());
        let elev = line.get(31..37).and_then(|s| s.trim().parse::<f64>().ok());
        let state = line.get(38..40).unwrap_or("").trim().to_string();
        let name = line.get(41..71).unwrap_or("").trim().to_string();
        let first_year = line.get(72..76).and_then(|s| s.trim().parse::<i32>().ok());
        let last_year = line.get(77..81).and_then(|s| s.trim().parse::<i32>().ok());

        if let (Some(lat), Some(lon), Some(elev), Some(fy), Some(ly)) =
            (lat, lon, elev, first_year, last_year)
        {
            stations.push(IgraStation {
                id: sid,
                lat,
                lon,
                elev,
                state,
                name,
                first_year: fy,
                last_year: ly,
            });
        }
    }
    stations
}

/// Download full period-of-record IGRA data for a station (zipped).
pub async fn download_igra_data(
    station_id: &str,
    output_path: &Path,
    progress_cb: &(dyn Fn(&str, &str) + Send + Sync),
) -> Result<(), String> {
    let url = format!("{IGRA_DATA_URL}/{station_id}-data.txt.zip");
    progress_cb("downloading", &format!("Downloading IGRA data for {station_id}..."));

    let resp = client()
        .get(&url)
        .timeout(std::time::Duration::from_secs(300))
        .send()
        .await
        .map_err(|e| format!("IGRA download failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("IGRA download failed: HTTP {}", resp.status()));
    }

    let bytes = resp.bytes().await.map_err(|e| format!("Read error: {e}"))?;

    // Extract from zip
    let cursor = std::io::Cursor::new(&bytes);
    let mut archive = zip::ZipArchive::new(cursor).map_err(|e| format!("Zip error: {e}"))?;

    if archive.is_empty() {
        return Err(format!("Empty zip file for station {station_id}"));
    }

    let mut entry = archive
        .by_index(0)
        .map_err(|e| format!("Zip entry error: {e}"))?;
    let mut out = fs::File::create(output_path).map_err(|e| format!("Create file: {e}"))?;
    std::io::copy(&mut entry, &mut out).map_err(|e| format!("Extract error: {e}"))?;

    progress_cb("done", &format!("Downloaded IGRA data for {station_id}"));
    Ok(())
}

/// Parse an IGRA header line, returning (station_id, year, month, day, hour).
fn parse_igra_header(line: &str) -> Option<(String, i32, i32, i32, i32)> {
    if !line.starts_with('#') {
        return None;
    }
    let parts: Vec<&str> = line[1..].split_whitespace().collect();
    if parts.len() < 5 {
        return None;
    }
    Some((
        parts[0].to_string(),
        parts[1].parse().ok()?,
        parts[2].parse().ok()?,
        parts[3].parse().ok()?,
        parts[4].parse().ok()?,
    ))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrimStats {
    pub total_soundings: usize,
    pub kept_soundings: usize,
}

/// Trim an IGRA file to only include soundings within [start_year, end_year].
pub fn trim_igra_to_years(
    input_path: &Path,
    output_path: &Path,
    start_year: i32,
    end_year: i32,
) -> Result<TrimStats, String> {
    let file = fs::File::open(input_path).map_err(|e| format!("Open error: {e}"))?;
    let reader = BufReader::new(file);
    let out = fs::File::create(output_path).map_err(|e| format!("Create error: {e}"))?;
    let mut writer = BufWriter::new(out);

    let mut total = 0usize;
    let mut kept = 0usize;
    let mut keeping = false;

    for line in reader.lines() {
        let line = line.map_err(|e| format!("Read line: {e}"))?;
        if line.starts_with('#') {
            total += 1;
            if let Some((_, year, _, _, _)) = parse_igra_header(&line) {
                if year >= start_year && year <= end_year {
                    keeping = true;
                    kept += 1;
                    writeln!(writer, "{line}").map_err(|e| format!("Write: {e}"))?;
                } else {
                    keeping = false;
                }
            } else {
                keeping = false;
            }
        } else if keeping {
            writeln!(writer, "{line}").map_err(|e| format!("Write: {e}"))?;
        }
    }

    Ok(TrimStats {
        total_soundings: total,
        kept_soundings: kept,
    })
}
