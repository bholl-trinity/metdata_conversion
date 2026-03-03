/// Geocoding — resolves user-provided locations to lat/lon.
///
/// Supports: street address (Nominatim), ICAO airport code (embedded CSV), direct lat/lon.
use crate::http_client::client;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GeoResult {
    pub lat: f64,
    pub lon: f64,
    #[serde(default)]
    pub display_name: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub country_code: String,
    pub is_us: bool,
}

/// Geocode a street address via Nominatim (OpenStreetMap).
pub async fn geocode_address(address: &str) -> Result<GeoResult, String> {
    let resp = client()
        .get("https://nominatim.openstreetmap.org/search")
        .query(&[
            ("q", address),
            ("format", "json"),
            ("limit", "1"),
            ("addressdetails", "1"),
        ])
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| format!("Geocode request failed: {e}"))?;

    let results: Vec<serde_json::Value> = resp
        .json()
        .await
        .map_err(|e| format!("Geocode parse failed: {e}"))?;

    let r = results
        .first()
        .ok_or_else(|| format!("No results found for address: {address}"))?;

    let lat: f64 = r["lat"]
        .as_str()
        .unwrap_or("0")
        .parse()
        .unwrap_or(0.0);
    let lon: f64 = r["lon"]
        .as_str()
        .unwrap_or("0")
        .parse()
        .unwrap_or(0.0);
    let display_name = r["display_name"].as_str().unwrap_or("").to_string();
    let country_code = r
        .get("address")
        .and_then(|a| a.get("country_code"))
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .to_uppercase();

    Ok(GeoResult {
        lat,
        lon,
        display_name,
        name: String::new(),
        country_code: country_code.clone(),
        is_us: country_code == "US",
    })
}

/// Look up an ICAO airport code from the embedded CSV database.
pub async fn geocode_airport(icao_code: &str) -> Result<GeoResult, String> {
    let code = icao_code.trim().to_uppercase();
    let csv_data = include_str!("../data/airports.csv");

    let mut rdr = csv::Reader::from_reader(csv_data.as_bytes());
    for record in rdr.records() {
        let record = record.map_err(|e| format!("CSV parse error: {e}"))?;
        let icao = record.get(5).unwrap_or("").trim().to_uppercase(); // icao column
        if icao == code {
            let lat: f64 = record.get(6).unwrap_or("0").trim().parse().unwrap_or(0.0);
            let lon: f64 = record.get(7).unwrap_or("0").trim().parse().unwrap_or(0.0);
            let name = record.get(1).unwrap_or("").trim().to_string();
            let cc = record.get(3).unwrap_or("").trim().to_uppercase();
            return Ok(GeoResult {
                lat,
                lon,
                display_name: name.clone(),
                name,
                country_code: cc.clone(),
                is_us: cc == "US",
            });
        }
    }

    // Fall back to Nominatim
    geocode_address(&format!("{code} airport")).await
}

/// Validate and return a direct lat/lon entry.
pub fn geocode_latlon(lat: f64, lon: f64) -> Result<GeoResult, String> {
    if !(-90.0..=90.0).contains(&lat) {
        return Err(format!("Invalid latitude: {lat}"));
    }
    if !(-180.0..=180.0).contains(&lon) {
        return Err(format!("Invalid longitude: {lon}"));
    }

    let is_us = is_conus(lat, lon);
    Ok(GeoResult {
        lat,
        lon,
        display_name: format!("{lat:.4}, {lon:.4}"),
        name: String::new(),
        country_code: if is_us { "US".to_string() } else { String::new() },
        is_us,
    })
}

/// Simple bounding-box check for continental US.
fn is_conus(lat: f64, lon: f64) -> bool {
    (24.0..=50.0).contains(&lat) && (-125.0..=-66.0).contains(&lon)
}

/// Haversine distance in km between two lat/lon points.
pub fn haversine_km(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    const R: f64 = 6371.0;
    let rlat1 = lat1.to_radians();
    let rlon1 = lon1.to_radians();
    let rlat2 = lat2.to_radians();
    let rlon2 = lon2.to_radians();
    let dlat = rlat2 - rlat1;
    let dlon = rlon2 - rlon1;
    let a = (dlat / 2.0).sin().powi(2) + rlat1.cos() * rlat2.cos() * (dlon / 2.0).sin().powi(2);
    R * 2.0 * a.sqrt().atan2((1.0 - a).sqrt())
}
