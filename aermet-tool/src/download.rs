/// Data download — acquires surface (GHCNh), upper air (IGRA), and 1-minute ASOS data.
use crate::ghcnh_to_isd;
use crate::http_client::client;
use crate::igra;
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

const GHCNH_BASE_URL: &str =
    "https://www.ncei.noaa.gov/data/global-historical-climatology-network-hourly/access";
const ONEMIN_BASE_URL: &str =
    "https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access";

/// Thread-safe progress callback type.
pub type ProgressCb = Arc<dyn Fn(&str, &str) + Send + Sync>;

#[derive(Debug, Clone, Serialize)]
pub struct SurfaceResult {
    pub ghcnh_path: String,
    pub isd_path: String,
    pub stats: ghcnh_to_isd::ConversionStats,
}

#[derive(Debug, Clone, Serialize)]
pub struct UpperAirResult {
    pub igra_path: String,
    pub stats: igra::TrimStats,
}

/// Download GHCNh data for a station.
pub async fn download_ghcnh(
    station_id: &str,
    output_dir: &Path,
    progress_cb: &ProgressCb,
) -> Result<PathBuf, String> {
    fs::create_dir_all(output_dir).ok();
    let filename = format!("GHCNh_{station_id}_por.psv");
    let url = format!("{GHCNH_BASE_URL}/{filename}");
    let output_path = output_dir.join(&filename);

    progress_cb(
        "downloading",
        &format!("Downloading GHCNh surface data for {station_id}..."),
    );

    let resp = client()
        .get(&url)
        .timeout(std::time::Duration::from_secs(300))
        .send()
        .await
        .map_err(|e| format!("Download failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("Download failed: HTTP {}", resp.status()));
    }

    let total = resp.content_length().unwrap_or(0);
    let bytes = resp.bytes().await.map_err(|e| format!("Read error: {e}"))?;

    if total > 0 {
        progress_cb("downloading", "Downloading surface data... 100%");
    }

    fs::write(&output_path, &bytes).map_err(|e| format!("Write error: {e}"))?;
    progress_cb("done", &format!("Downloaded {filename}"));
    Ok(output_path)
}

/// Convert GHCNh PSV to ISD format.
pub fn convert_surface_data(
    ghcnh_path: &Path,
    isd_output_path: &Path,
    progress_cb: &ProgressCb,
) -> Result<ghcnh_to_isd::ConversionStats, String> {
    progress_cb("converting", "Converting GHCNh to ISD format...");

    let stats = ghcnh_to_isd::convert_ghcnh_file(ghcnh_path, isd_output_path, None)?;

    progress_cb(
        "done",
        &format!("Converted {} records to ISD format", stats.converted),
    );
    Ok(stats)
}

/// Download GHCNh and convert to ISD in one step.
pub async fn download_and_convert_surface(
    station_id: &str,
    output_dir: &Path,
    progress_cb: &ProgressCb,
) -> Result<SurfaceResult, String> {
    let ghcnh_path = download_ghcnh(station_id, output_dir, progress_cb).await?;
    let isd_path = output_dir.join(format!("{station_id}.ish"));
    let stats = convert_surface_data(&ghcnh_path, &isd_path, progress_cb)?;
    Ok(SurfaceResult {
        ghcnh_path: ghcnh_path.to_string_lossy().to_string(),
        isd_path: isd_path.to_string_lossy().to_string(),
        stats,
    })
}

/// Download full IGRA file and trim to years of interest.
pub async fn download_and_trim_upper_air(
    igra_station_id: &str,
    output_dir: &Path,
    start_year: i32,
    end_year: i32,
    progress_cb: &ProgressCb,
) -> Result<UpperAirResult, String> {
    fs::create_dir_all(output_dir).ok();
    let full_path = output_dir.join(format!("{igra_station_id}_full.dat"));
    let trimmed_path =
        output_dir.join(format!("{igra_station_id}_{start_year}_{end_year}.dat"));

    igra::download_igra_data(igra_station_id, &full_path, &**progress_cb).await?;

    progress_cb(
        "trimming",
        &format!("Trimming IGRA data to {start_year}-{end_year}..."),
    );
    let stats = igra::trim_igra_to_years(&full_path, &trimmed_path, start_year, end_year)?;

    progress_cb(
        "done",
        &format!(
            "Trimmed IGRA: kept {} of {} soundings",
            stats.kept_soundings, stats.total_soundings
        ),
    );

    // Remove the full file to save space
    fs::remove_file(&full_path).ok();

    Ok(UpperAirResult {
        igra_path: trimmed_path.to_string_lossy().to_string(),
        stats,
    })
}

/// Download 1-minute ASOS data for a station and year.
pub async fn download_one_minute_asos(
    station_wban: &str,
    year: i32,
    output_dir: &Path,
    progress_cb: &ProgressCb,
) -> Option<String> {
    fs::create_dir_all(output_dir).ok();
    let wban = format!("{:0>5}", station_wban);
    let filename = format!("{wban}.dat");
    let url = format!("{ONEMIN_BASE_URL}/{year}/{filename}");
    let output_path = output_dir.join(format!("onemin_{wban}_{year}.dat"));

    progress_cb(
        "downloading",
        &format!("Downloading 1-min ASOS for WBAN {wban}, year {year}..."),
    );

    let resp = match client()
        .get(&url)
        .timeout(std::time::Duration::from_secs(120))
        .send()
        .await
    {
        Ok(r) => r,
        Err(_) => {
            progress_cb("error", &format!("Failed to download 1-min data for {year}"));
            return None;
        }
    };

    if resp.status().as_u16() == 404 {
        progress_cb(
            "skipped",
            &format!("No 1-min data available for WBAN {wban}, {year}"),
        );
        return None;
    }

    if !resp.status().is_success() {
        progress_cb("error", &format!("Failed to download 1-min data for {year}"));
        return None;
    }

    let bytes = match resp.bytes().await {
        Ok(b) => b,
        Err(_) => {
            progress_cb("error", &format!("Failed to read 1-min data for {year}"));
            return None;
        }
    };

    if fs::write(&output_path, &bytes).is_err() {
        return None;
    }

    progress_cb("done", &format!("Downloaded 1-min ASOS for {year}"));
    Some(output_path.to_string_lossy().to_string())
}
