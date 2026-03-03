/// Station discovery — find nearby surface (GHCNh/ISD) and upper air (IGRA) stations.
use crate::geocode::haversine_km;
use crate::http_client::client;
use crate::igra;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

const GHCNH_STATION_LIST_URL: &str =
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt";
const GHCNH_INVENTORY_URL: &str =
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-inventory.txt";
const ISD_HISTORY_URL: &str = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv";

fn data_dir() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));
    exe_dir.join("data")
}

// ---------------------------------------------------------------------------
// GHCNh surface stations
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GhcnhStation {
    pub ghcnh_id: String,
    pub lat: f64,
    pub lon: f64,
    pub elev: Option<f64>,
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub country: String,
    #[serde(default)]
    pub wmo_id: String,
    #[serde(default)]
    pub icao: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub distance_km: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub first_year: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_year: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completeness: Option<CompletenessInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompletenessInfo {
    pub complete_months: i32,
    pub total_months: i32,
    pub pct_complete: f64,
}

async fn ensure_file(url: &str, filename: &str, timeout_secs: u64) -> Result<PathBuf, String> {
    let dir = data_dir();
    fs::create_dir_all(&dir).ok();
    let path = dir.join(filename);
    if path.exists() {
        return Ok(path);
    }
    let resp = client()
        .get(url)
        .timeout(std::time::Duration::from_secs(timeout_secs))
        .send()
        .await
        .map_err(|e| format!("Download {filename}: {e}"))?;
    let text = resp.text().await.map_err(|e| format!("Read {filename}: {e}"))?;
    fs::write(&path, &text).map_err(|e| format!("Write {filename}: {e}"))?;
    Ok(path)
}

pub async fn ensure_ghcnh_station_list() -> Result<PathBuf, String> {
    ensure_file(GHCNH_STATION_LIST_URL, "ghcnh-station-list.txt", 60).await
}

pub async fn ensure_ghcnh_inventory() -> Result<PathBuf, String> {
    ensure_file(GHCNH_INVENTORY_URL, "ghcnh-inventory.txt", 120).await
}

pub async fn ensure_isd_station_list() -> Result<PathBuf, String> {
    ensure_file(ISD_HISTORY_URL, "isd-history.csv", 60).await
}

pub async fn ensure_igra_station_list() -> Result<PathBuf, String> {
    ensure_file(igra::IGRA_STATION_LIST_URL, "igra2-station-list.txt", 60).await
}

fn load_ghcnh_stations(text: &str) -> Vec<GhcnhStation> {
    let mut stations = Vec::new();
    for line in text.lines() {
        if line.trim().len() < 40 {
            continue;
        }
        let sid = line.get(0..11).unwrap_or("").trim().to_string();
        let lat = line.get(12..20).and_then(|s| s.trim().parse::<f64>().ok());
        let lon = line.get(21..30).and_then(|s| s.trim().parse::<f64>().ok());
        let elev_str = line.get(31..37).unwrap_or("").trim();
        let elev = if elev_str.is_empty() || elev_str == "-999.9" {
            None
        } else {
            elev_str.parse::<f64>().ok()
        };
        let state = line.get(38..40).unwrap_or("").trim().to_string();
        let name = line.get(41..71).unwrap_or("").trim().to_string();
        let wmo_id = line.get(80..85).unwrap_or("").trim().to_string();
        let icao = line.get(86..90).unwrap_or("").trim().to_string();
        let country = if sid.len() >= 2 {
            sid[..2].to_string()
        } else {
            String::new()
        };

        if let (Some(lat), Some(lon)) = (lat, lon) {
            stations.push(GhcnhStation {
                ghcnh_id: sid,
                lat,
                lon,
                elev,
                state,
                name,
                country,
                wmo_id,
                icao,
                distance_km: None,
                first_year: None,
                last_year: None,
                completeness: None,
            });
        }
    }
    stations
}

type Inventory = HashMap<String, HashMap<(i32, i32), i32>>;

fn load_ghcnh_inventory(text: &str) -> Inventory {
    let mut inventory: Inventory = HashMap::new();
    for line in text.lines() {
        if line.trim().len() < 20 {
            continue;
        }
        let sid = line.get(0..11).unwrap_or("").trim();
        let year = line.get(12..16).and_then(|s| s.trim().parse::<i32>().ok());
        let month = line.get(17..19).and_then(|s| s.trim().parse::<i32>().ok());
        let count = line.get(20..).and_then(|s| s.trim().parse::<i32>().ok());
        if let (Some(y), Some(m), Some(c)) = (year, month, count) {
            inventory
                .entry(sid.to_string())
                .or_default()
                .insert((y, m), c);
        }
    }
    inventory
}

fn check_ghcnh_completeness(
    inv: &Inventory,
    station_id: &str,
    start_year: i32,
    end_year: i32,
    min_obs: i32,
) -> CompletenessInfo {
    let months = inv.get(station_id);
    let mut total = 0;
    let mut complete = 0;
    for year in start_year..=end_year {
        for month in 1..=12 {
            total += 1;
            let count = months
                .and_then(|m| m.get(&(year, month)))
                .copied()
                .unwrap_or(0);
            if count >= min_obs {
                complete += 1;
            }
        }
    }
    let pct = if total > 0 {
        (complete as f64 / total as f64 * 100.0 * 10.0).round() / 10.0
    } else {
        0.0
    };
    CompletenessInfo {
        complete_months: complete,
        total_months: total,
        pct_complete: pct,
    }
}

fn year_range_from_inventory(inv: &Inventory, station_id: &str) -> (Option<i32>, Option<i32>) {
    match inv.get(station_id) {
        Some(months) => {
            let years: Vec<i32> = months.keys().map(|(y, _)| *y).collect();
            (years.iter().copied().min(), years.iter().copied().max())
        }
        None => (None, None),
    }
}

pub async fn find_nearby_surface_stations(
    lat: f64,
    lon: f64,
    start_year: i32,
    end_year: i32,
    max_distance_km: f64,
) -> Result<Vec<serde_json::Value>, String> {
    // Try GHCNh first
    match try_ghcnh_stations(lat, lon, start_year, end_year, max_distance_km).await {
        Ok(stations) => return Ok(stations),
        Err(_) => {}
    }

    // Fallback to ISD
    find_isd_stations(lat, lon, start_year, end_year, max_distance_km).await
}

async fn try_ghcnh_stations(
    lat: f64,
    lon: f64,
    start_year: i32,
    end_year: i32,
    max_distance_km: f64,
) -> Result<Vec<serde_json::Value>, String> {
    let stn_path = ensure_ghcnh_station_list().await?;
    let stn_text = fs::read_to_string(&stn_path).map_err(|e| format!("Read: {e}"))?;
    let all_stations = load_ghcnh_stations(&stn_text);

    // Try loading inventory
    let inv = match ensure_ghcnh_inventory().await {
        Ok(inv_path) => {
            let inv_text = fs::read_to_string(&inv_path).unwrap_or_default();
            Some(load_ghcnh_inventory(&inv_text))
        }
        Err(_) => None,
    };

    let mut candidates = Vec::new();
    for s in &all_stations {
        let dist = haversine_km(lat, lon, s.lat, s.lon);
        if dist > max_distance_km {
            continue;
        }

        let mut sc = s.clone();
        sc.distance_km = Some((dist * 10.0).round() / 10.0);

        if let Some(ref inv) = inv {
            let (first, last) = year_range_from_inventory(inv, &s.ghcnh_id);
            sc.first_year = first;
            sc.last_year = last;
            if let (Some(first), Some(last)) = (first, last) {
                if last < start_year || first > end_year {
                    continue;
                }
                sc.completeness = Some(check_ghcnh_completeness(
                    inv,
                    &s.ghcnh_id,
                    start_year,
                    end_year,
                    200,
                ));
            }
        }

        candidates.push(sc);
    }

    candidates.sort_by(|a, b| {
        a.distance_km
            .unwrap_or(f64::MAX)
            .partial_cmp(&b.distance_km.unwrap_or(f64::MAX))
            .unwrap()
    });
    candidates.truncate(20);

    let json: Vec<serde_json::Value> = candidates
        .iter()
        .map(|s| serde_json::to_value(s).unwrap_or_default())
        .collect();
    Ok(json)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct IsdStation {
    usaf: String,
    wban: String,
    name: String,
    country: String,
    state: String,
    icao: String,
    lat: f64,
    lon: f64,
    elev: Option<f64>,
    first_year: i32,
    last_year: i32,
    begin: String,
    end: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    distance_km: Option<f64>,
}

async fn find_isd_stations(
    lat: f64,
    lon: f64,
    start_year: i32,
    end_year: i32,
    max_distance_km: f64,
) -> Result<Vec<serde_json::Value>, String> {
    let path = ensure_isd_station_list().await?;
    let text = fs::read_to_string(&path).map_err(|e| format!("Read ISD: {e}"))?;
    let mut rdr = csv::Reader::from_reader(text.as_bytes());

    let mut candidates = Vec::new();
    for result in rdr.records() {
        let row = match result {
            Ok(r) => r,
            Err(_) => continue,
        };
        let lat_s = row.get(6).unwrap_or("").trim();
        let lon_s = row.get(7).unwrap_or("").trim();
        if lat_s.is_empty() || lon_s.is_empty() {
            continue;
        }
        let slat: f64 = match lat_s.parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let slon: f64 = match lon_s.parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        if slat == 0.0 && slon == 0.0 {
            continue;
        }

        let dist = haversine_km(lat, lon, slat, slon);
        if dist > max_distance_km {
            continue;
        }

        let begin = row.get(10).unwrap_or("").trim().to_string();
        let end = row.get(11).unwrap_or("").trim().to_string();
        let first_year: i32 = begin
            .get(..4)
            .and_then(|s| s.parse().ok())
            .unwrap_or(9999);
        let last_year: i32 = end.get(..4).and_then(|s| s.parse().ok()).unwrap_or(0);

        if last_year < start_year || first_year > end_year {
            continue;
        }

        let elev_s = row.get(8).unwrap_or("").trim();

        candidates.push(IsdStation {
            usaf: row.get(0).unwrap_or("999999").trim().to_string(),
            wban: row.get(1).unwrap_or("99999").trim().to_string(),
            name: row.get(2).unwrap_or("").trim().to_string(),
            country: row.get(3).unwrap_or("").trim().to_string(),
            state: row.get(4).unwrap_or("").trim().to_string(),
            icao: row.get(5).unwrap_or("").trim().to_string(),
            lat: slat,
            lon: slon,
            elev: if elev_s.is_empty() {
                None
            } else {
                elev_s.parse().ok()
            },
            first_year,
            last_year,
            begin,
            end,
            distance_km: Some((dist * 10.0).round() / 10.0),
        });
    }

    candidates.sort_by(|a, b| {
        a.distance_km
            .unwrap_or(f64::MAX)
            .partial_cmp(&b.distance_km.unwrap_or(f64::MAX))
            .unwrap()
    });
    candidates.truncate(20);

    let json: Vec<serde_json::Value> = candidates
        .iter()
        .map(|s| serde_json::to_value(s).unwrap_or_default())
        .collect();
    Ok(json)
}

pub async fn find_nearby_upper_air_stations(
    lat: f64,
    lon: f64,
    start_year: i32,
    end_year: i32,
    max_distance_km: f64,
) -> Result<Vec<serde_json::Value>, String> {
    let path = ensure_igra_station_list().await?;
    let text = fs::read_to_string(&path).map_err(|e| format!("Read IGRA: {e}"))?;
    let all_stations = igra::parse_igra_station_list(&text);

    let mut candidates: Vec<serde_json::Value> = Vec::new();
    for s in &all_stations {
        let dist = haversine_km(lat, lon, s.lat, s.lon);
        if dist > max_distance_km {
            continue;
        }
        if s.last_year < start_year || s.first_year > end_year {
            continue;
        }
        let mut val = serde_json::to_value(s).unwrap_or_default();
        val["distance_km"] = serde_json::json!(((dist * 10.0).round() / 10.0));
        candidates.push(val);
    }

    candidates.sort_by(|a, b| {
        let da = a["distance_km"].as_f64().unwrap_or(f64::MAX);
        let db = b["distance_km"].as_f64().unwrap_or(f64::MAX);
        da.partial_cmp(&db).unwrap()
    });
    candidates.truncate(10);

    Ok(candidates)
}
