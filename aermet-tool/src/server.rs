/// HTTP server — axum routes serving the API and embedded static files.
use axum::{
    body::Body,
    extract::{Path as AxumPath, Query},
    http::{header, StatusCode},
    response::{IntoResponse, Json, Response},
    routing::{get, post},
    Router,
};
use rust_embed::Embed;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::{
    aermet_runner, aersurface, completeness, download,
    aerminute,
    geocode, project, stations,
};

// ---------------------------------------------------------------------------
// Embedded static files
// ---------------------------------------------------------------------------

#[derive(Embed)]
#[folder = "static/"]
struct StaticAssets;

async fn serve_static(AxumPath(path): AxumPath<String>) -> Response {
    match StaticAssets::get(&path) {
        Some(file) => {
            let mime = mime_guess::from_path(&path)
                .first_or_octet_stream()
                .to_string();
            Response::builder()
                .header(header::CONTENT_TYPE, mime)
                .body(Body::from(file.data.to_vec()))
                .unwrap()
        }
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

async fn serve_index() -> Response {
    match StaticAssets::get("index.html") {
        Some(file) => Response::builder()
            .header(header::CONTENT_TYPE, "text/html")
            .body(Body::from(file.data.to_vec()))
            .unwrap(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

// ---------------------------------------------------------------------------
// Progress tracking (shared state)
// ---------------------------------------------------------------------------

#[derive(Clone, serde::Serialize)]
struct ProgressEntry {
    stage: String,
    message: String,
    time: f64,
}

type ProgressStore = Arc<Mutex<HashMap<String, Vec<ProgressEntry>>>>;

fn now_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

#[derive(Clone)]
pub struct AppState {
    progress: ProgressStore,
}

impl AppState {
    fn add_progress(&self, project_id: &str, stage: &str, message: &str) {
        let mut store = self.progress.lock().unwrap();
        store
            .entry(project_id.to_string())
            .or_default()
            .push(ProgressEntry {
                stage: stage.to_string(),
                message: message.to_string(),
                time: now_ts(),
            });
    }
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

pub fn create_router() -> Router {
    let state = AppState {
        progress: Arc::new(Mutex::new(HashMap::new())),
    };

    Router::new()
        // Static files
        .route("/", get(serve_index))
        .route("/{*path}", get(serve_static))
        // API routes
        .route("/api/geocode", post(api_geocode))
        .route("/api/stations/surface", get(api_surface_stations))
        .route("/api/stations/upperair", get(api_upper_air_stations))
        .route("/api/project/create", post(api_create_project))
        .route("/api/project/{project_id}", get(api_get_project))
        .route("/api/project/{project_id}/update", post(api_update_project))
        .route(
            "/api/project/{project_id}/download-data",
            post(api_download_data),
        )
        .route(
            "/api/project/{project_id}/progress",
            get(api_progress),
        )
        .route(
            "/api/project/{project_id}/run-aermet",
            post(api_run_aermet),
        )
        .route(
            "/api/project/{project_id}/completeness",
            get(api_completeness),
        )
        .route(
            "/api/project/{project_id}/aersurface",
            post(api_aersurface),
        )
        .route("/api/aersurface/reference", get(api_land_use_reference))
        .route(
            "/api/project/{project_id}/download",
            get(api_download_output),
        )
        .route(
            "/api/project/{project_id}/download/{filename}",
            get(api_download_file),
        )
        .route("/api/init", post(api_init))
        .with_state(state)
}

// ---------------------------------------------------------------------------
// Geocoding
// ---------------------------------------------------------------------------

async fn api_geocode(Json(data): Json<Value>) -> impl IntoResponse {
    let method = data["method"].as_str().unwrap_or("address");
    let result = match method {
        "address" => {
            let address = data["address"].as_str().unwrap_or("");
            geocode::geocode_address(address).await
        }
        "airport" => {
            let code = data["code"].as_str().unwrap_or("");
            geocode::geocode_airport(code).await
        }
        "latlon" => {
            let lat = data["lat"].as_f64().unwrap_or(0.0);
            let lon = data["lon"].as_f64().unwrap_or(0.0);
            geocode::geocode_latlon(lat, lon)
        }
        _ => Err(format!("Unknown method: {method}")),
    };

    match result {
        Ok(geo) => Json(serde_json::to_value(geo).unwrap()).into_response(),
        Err(e) => (StatusCode::BAD_REQUEST, Json(json!({"error": e}))).into_response(),
    }
}

// ---------------------------------------------------------------------------
// Station discovery
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct StationQuery {
    lat: f64,
    lon: f64,
    start_year: i32,
    end_year: i32,
    max_distance: Option<f64>,
}

async fn api_surface_stations(Query(q): Query<StationQuery>) -> impl IntoResponse {
    let max_dist = q.max_distance.unwrap_or(150.0);
    match stations::find_nearby_surface_stations(q.lat, q.lon, q.start_year, q.end_year, max_dist)
        .await
    {
        Ok(stations) => Json(Value::Array(stations)).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e}))).into_response(),
    }
}

async fn api_upper_air_stations(Query(q): Query<StationQuery>) -> impl IntoResponse {
    let max_dist = q.max_distance.unwrap_or(400.0);
    match stations::find_nearby_upper_air_stations(q.lat, q.lon, q.start_year, q.end_year, max_dist)
        .await
    {
        Ok(stations) => Json(Value::Array(stations)).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e}))).into_response(),
    }
}

// ---------------------------------------------------------------------------
// Project management
// ---------------------------------------------------------------------------

async fn api_create_project(Json(data): Json<Value>) -> impl IntoResponse {
    let req: project::CreateProjectRequest = match serde_json::from_value(data) {
        Ok(r) => r,
        Err(e) => {
            return (StatusCode::BAD_REQUEST, Json(json!({"error": e.to_string()}))).into_response()
        }
    };

    match project::create_project(req) {
        Ok(p) => Json(serde_json::to_value(p).unwrap()).into_response(),
        Err(e) => {
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e}))).into_response()
        }
    }
}

async fn api_get_project(AxumPath(project_id): AxumPath<String>) -> impl IntoResponse {
    match project::load_project(&project_id) {
        Ok(p) => Json(serde_json::to_value(p).unwrap()).into_response(),
        Err(e) => (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    }
}

async fn api_update_project(
    AxumPath(project_id): AxumPath<String>,
    Json(data): Json<Value>,
) -> impl IntoResponse {
    match project::load_project(&project_id) {
        Ok(mut p) => match project::update_project(&mut p, data) {
            Ok(_) => Json(serde_json::to_value(p).unwrap()).into_response(),
            Err(e) => {
                (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e}))).into_response()
            }
        },
        Err(e) => (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    }
}

// ---------------------------------------------------------------------------
// Data download (background task)
// ---------------------------------------------------------------------------

async fn api_download_data(
    axum::extract::State(state): axum::extract::State<AppState>,
    AxumPath(project_id): AxumPath<String>,
    Json(data): Json<Value>,
) -> impl IntoResponse {
    let proj = match project::load_project(&project_id) {
        Ok(p) => p,
        Err(e) => return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    };

    let pid = project_id.clone();
    let st = state.clone();

    tokio::spawn(async move {
        let pcb: download::ProgressCb = Arc::new(move |stage: &str, msg: &str| {
            st.add_progress(&pid, stage, msg);
        });

        let sf = data.get("surface_station").cloned().unwrap_or_default();
        let ua = data.get("upper_air_station").cloned().unwrap_or_default();
        let start_year = proj.data_period.start_year;
        let end_year = proj.data_period.end_year;

        // Update project with station selections
        let mut proj = proj;
        let _ = project::update_project(
            &mut proj,
            json!({"surface_station": sf, "upper_air_station": ua, "status": "downloading"}),
        );

        // Download surface data
        pcb("surface", "Downloading surface data...");
        let ghcnh_station_id = sf
            .get("ghcnh_id")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                let wban = sf.get("wban").and_then(|v| v.as_str()).unwrap_or("99999");
                if wban != "99999" {
                    format!("USW00{wban}")
                } else {
                    sf.get("usaf")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string()
                }
            });

        let surface_dir = std::path::Path::new(&proj.dir).join("surface");
        let surface_result = download::download_and_convert_surface(
            &ghcnh_station_id,
            &surface_dir,
            &pcb,
        )
        .await;

        match surface_result {
            Ok(sr) => {
                let mut results = proj.results.as_object().cloned().unwrap_or_default();
                results.insert(
                    "surface".to_string(),
                    json!({"isd_path": sr.isd_path, "stats": sr.stats}),
                );
                let _ = project::update_project(
                    &mut proj,
                    json!({"results": Value::Object(results)}),
                );
            }
            Err(e) => {
                pcb("error", &e);
                return;
            }
        }

        // Download upper air data
        pcb("upper_air", "Downloading upper air data...");
        let ua_id = ua.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let ua_dir = std::path::Path::new(&proj.dir).join("upper_air");
        let ua_result = download::download_and_trim_upper_air(
            ua_id,
            &ua_dir,
            start_year,
            end_year,
            &pcb,
        )
        .await;

        match ua_result {
            Ok(ur) => {
                let mut results = proj.results.as_object().cloned().unwrap_or_default();
                results.insert(
                    "upper_air".to_string(),
                    json!({"igra_path": ur.igra_path, "stats": ur.stats}),
                );
                let _ = project::update_project(
                    &mut proj,
                    json!({"results": Value::Object(results)}),
                );
            }
            Err(e) => {
                pcb("error", &e);
                return;
            }
        }

        // Download 1-minute ASOS if applicable
        let mut onemin_files: HashMap<String, String> = HashMap::new();
        let wban = sf.get("wban").and_then(|v| v.as_str()).unwrap_or("99999");
        if proj.is_us && wban != "99999" {
            if aerminute::check_aerminute_availability(wban, start_year, end_year) {
                let onemin_dir = std::path::Path::new(&proj.dir).join("one_minute");
                for yr in start_year..=end_year {
                    if let Some(path) =
                        download::download_one_minute_asos(wban, yr, &onemin_dir, &pcb).await
                    {
                        onemin_files.insert(yr.to_string(), path);
                    }
                }
            }
        }

        let mut results = proj.results.as_object().cloned().unwrap_or_default();
        results.insert(
            "onemin_files".to_string(),
            serde_json::to_value(&onemin_files).unwrap(),
        );
        let _ = project::update_project(
            &mut proj,
            json!({"results": Value::Object(results), "status": "downloaded"}),
        );

        pcb("complete", "All data downloaded successfully");
    });

    Json(json!({"status": "started", "message": "Download started"})).into_response()
}

// ---------------------------------------------------------------------------
// Progress polling
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct ProgressQuery {
    since: Option<f64>,
}

async fn api_progress(
    axum::extract::State(state): axum::extract::State<AppState>,
    AxumPath(project_id): AxumPath<String>,
    Query(q): Query<ProgressQuery>,
) -> Json<Value> {
    let since = q.since.unwrap_or(0.0);
    let store = state.progress.lock().unwrap();
    let entries: Vec<&ProgressEntry> = store
        .get(&project_id)
        .map(|v| v.iter().filter(|e| e.time > since).collect())
        .unwrap_or_default();
    Json(serde_json::to_value(entries).unwrap())
}

// ---------------------------------------------------------------------------
// AERMET execution (background task)
// ---------------------------------------------------------------------------

async fn api_run_aermet(
    axum::extract::State(state): axum::extract::State<AppState>,
    AxumPath(project_id): AxumPath<String>,
    Json(data): Json<Value>,
) -> impl IntoResponse {
    let proj = match project::load_project(&project_id) {
        Ok(p) => p,
        Err(e) => return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    };

    let pid = project_id.clone();
    let st = state.clone();

    tokio::spawn(async move {
        let pcb: download::ProgressCb = Arc::new(move |stage: &str, msg: &str| {
            st.add_progress(&pid, stage, msg);
        });

        let mut proj = proj;
        let _ = project::update_project(&mut proj, json!({"status": "running_aermet"}));

        let sf = proj.surface_station.clone().unwrap_or_default();
        let ua = proj.upper_air_station.clone().unwrap_or_default();
        let start_year = proj.data_period.start_year;
        let end_year = proj.data_period.end_year;

        let results_data = proj.results.clone();
        let isd_path = results_data
            .get("surface")
            .and_then(|s| s.get("isd_path"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let igra_path = results_data
            .get("upper_air")
            .and_then(|s| s.get("igra_path"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let onemin_files: HashMap<String, String> = results_data
            .get("onemin_files")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();

        let sf_usaf = sf.get("usaf").and_then(|v| v.as_str()).unwrap_or("999999");
        let sf_wban = sf.get("wban").and_then(|v| v.as_str()).unwrap_or("99999");
        let sf_id = format!("{sf_usaf}{sf_wban}");
        let sf_lat = sf
            .get("refined_lat")
            .or_else(|| sf.get("lat"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let sf_lon = sf
            .get("refined_lon")
            .or_else(|| sf.get("lon"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let ua_id = ua.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let ua_lat = ua.get("lat").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let ua_lon = ua.get("lon").and_then(|v| v.as_f64()).unwrap_or(0.0);

        let aersurface_file = data
            .get("aersurface_file")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let manual_chars: Option<aermet_runner::ManualSurfaceChars> = data
            .get("manual_surface_chars")
            .and_then(|v| serde_json::from_value(v.clone()).ok());
        let anemometer_height = data
            .get("anemometer_height")
            .and_then(|v| v.as_f64())
            .unwrap_or(10.0);

        let aermet_dir = std::path::Path::new(&proj.dir).join("aermet");
        std::fs::create_dir_all(aermet_dir.join("output")).ok();

        let mut sfc_files: Vec<String> = Vec::new();
        let mut pfl_files: Vec<String> = Vec::new();
        let mut year_results: HashMap<String, Value> = HashMap::new();

        for yr in start_year..=end_year {
            pcb("aermet", &format!("Processing year {yr}..."));

            let onemin = onemin_files.get(&yr.to_string()).map(|s| s.as_str());
            let mc_ref = manual_chars.as_ref();

            let result = aermet_runner::run_aermet_all_stages(
                &aermet_dir,
                yr,
                &isd_path,
                &igra_path,
                &sf_id,
                sf_lat,
                sf_lon,
                ua_id,
                ua_lat,
                ua_lon,
                aersurface_file.as_deref(),
                onemin,
                anemometer_height,
                mc_ref,
                &*pcb,
            );

            let mut yr_val = serde_json::to_value(&result).unwrap_or_default();

            if result.success {
                sfc_files.push(result.sfc_path.clone());
                pfl_files.push(result.pfl_path.clone());

                let comp = completeness::check_completeness(
                    std::path::Path::new(&result.sfc_path),
                    proj.completeness.threshold,
                    &proj.completeness.basis,
                    Some(yr),
                );
                yr_val["completeness"] = serde_json::to_value(&comp).unwrap_or_default();

                if !comp.passes {
                    let fail_msg = comp.failures.join("; ");
                    pcb(
                        "warning",
                        &format!("Year {yr} below completeness threshold: {fail_msg}"),
                    );
                }
            }

            year_results.insert(yr.to_string(), yr_val);
        }

        // Combine multi-year files
        let output_dir = std::path::Path::new(&proj.dir).join("output");
        std::fs::create_dir_all(&output_dir).ok();

        let output_option = data
            .get("output_option")
            .and_then(|v| v.as_str())
            .unwrap_or("both");
        let mut final_files: HashMap<String, String> = HashMap::new();

        if (output_option == "combined" || output_option == "both") && sfc_files.len() > 1 {
            let combined_sfc = output_dir.join("combined.SFC");
            let combined_pfl = output_dir.join("combined.PFL");
            let _ = aermet_runner::combine_sfc_files(&sfc_files, &combined_sfc);
            let _ = aermet_runner::combine_pfl_files(&pfl_files, &combined_pfl);
            final_files.insert(
                "combined_sfc".to_string(),
                combined_sfc.to_string_lossy().to_string(),
            );
            final_files.insert(
                "combined_pfl".to_string(),
                combined_pfl.to_string_lossy().to_string(),
            );
        }

        if output_option == "individual" || output_option == "both" {
            for yr in start_year..=end_year {
                if let Some(yr_data) = year_results.get(&yr.to_string()) {
                    if yr_data.get("success").and_then(|v| v.as_bool()).unwrap_or(false) {
                        if let Some(sfc) = yr_data.get("sfc_path").and_then(|v| v.as_str()) {
                            final_files.insert(format!("{yr}_sfc"), sfc.to_string());
                        }
                        if let Some(pfl) = yr_data.get("pfl_path").and_then(|v| v.as_str()) {
                            final_files.insert(format!("{yr}_pfl"), pfl.to_string());
                        }
                    }
                }
            }
        }

        let mut all_results = results_data.as_object().cloned().unwrap_or_default();
        all_results.insert("year_results".to_string(), json!(year_results));
        all_results.insert("final_files".to_string(), json!(final_files));

        let _ = project::update_project(
            &mut proj,
            json!({"status": "complete", "results": Value::Object(all_results)}),
        );

        pcb("complete", "AERMET processing complete");
    });

    Json(json!({"status": "started", "message": "AERMET processing started"})).into_response()
}

// ---------------------------------------------------------------------------
// Completeness
// ---------------------------------------------------------------------------

async fn api_completeness(AxumPath(project_id): AxumPath<String>) -> impl IntoResponse {
    let proj = match project::load_project(&project_id) {
        Ok(p) => p,
        Err(e) => return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    };

    let year_results = proj
        .results
        .get("year_results")
        .cloned()
        .unwrap_or_default();

    let mut completeness_data = serde_json::Map::new();
    if let Value::Object(yr_map) = year_results {
        for (yr_str, yr_data) in yr_map {
            if let Some(comp) = yr_data.get("completeness") {
                completeness_data.insert(yr_str, comp.clone());
            }
        }
    }

    Json(Value::Object(completeness_data)).into_response()
}

// ---------------------------------------------------------------------------
// AERSURFACE
// ---------------------------------------------------------------------------

async fn api_aersurface(
    AxumPath(project_id): AxumPath<String>,
    Json(data): Json<Value>,
) -> impl IntoResponse {
    let proj = match project::load_project(&project_id) {
        Ok(p) => p,
        Err(e) => return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    };

    let work_dir = std::path::Path::new(&proj.dir).join("aermet");
    let nlcd_path = data["nlcd_path"].as_str().unwrap_or("");
    let center_lat = data["center_lat"].as_f64().unwrap_or(0.0);
    let center_lon = data["center_lon"].as_f64().unwrap_or(0.0);
    let is_airport = data["is_airport"].as_bool().unwrap_or(true);

    match aersurface::generate_control_file(&work_dir, nlcd_path, center_lat, center_lon, is_airport)
    {
        Ok(ctrl_path) => {
            let result = aersurface::run_aersurface(&ctrl_path, &work_dir);
            Json(serde_json::to_value(result).unwrap()).into_response()
        }
        Err(e) => {
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e}))).into_response()
        }
    }
}

async fn api_land_use_reference() -> Json<Value> {
    Json(serde_json::to_value(aersurface::land_use_reference()).unwrap())
}

// ---------------------------------------------------------------------------
// Download output
// ---------------------------------------------------------------------------

async fn api_download_output(AxumPath(project_id): AxumPath<String>) -> impl IntoResponse {
    let proj = match project::load_project(&project_id) {
        Ok(p) => p,
        Err(e) => return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    };

    let final_files: HashMap<String, String> = proj
        .results
        .get("final_files")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_default();

    if final_files.is_empty() {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({"error": "No output files available"})),
        )
            .into_response();
    }

    let zip_path = std::path::Path::new(&proj.dir)
        .join("output")
        .join("aermet_output.zip");

    let file = match std::fs::File::create(&zip_path) {
        Ok(f) => f,
        Err(e) => {
            return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()})))
                .into_response()
        }
    };

    let mut zip_writer = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    for (_label, fpath) in &final_files {
        let p = std::path::Path::new(fpath);
        if p.exists() {
            let arcname = p.file_name().unwrap_or_default().to_string_lossy();
            if zip_writer.start_file(arcname.as_ref(), options).is_ok() {
                if let Ok(data) = std::fs::read(fpath) {
                    use std::io::Write;
                    let _ = zip_writer.write_all(&data);
                }
            }
        }
    }
    let _ = zip_writer.finish();

    match std::fs::read(&zip_path) {
        Ok(data) => Response::builder()
            .header(header::CONTENT_TYPE, "application/zip")
            .header(
                header::CONTENT_DISPOSITION,
                "attachment; filename=\"aermet_output.zip\"",
            )
            .body(Body::from(data))
            .unwrap()
            .into_response(),
        Err(e) => {
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()})))
                .into_response()
        }
    }
}

async fn api_download_file(
    AxumPath((project_id, filename)): AxumPath<(String, String)>,
) -> impl IntoResponse {
    let proj = match project::load_project(&project_id) {
        Ok(p) => p,
        Err(e) => return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response(),
    };

    let file_path = std::path::Path::new(&proj.dir).join("output").join(&filename);
    match std::fs::read(&file_path) {
        Ok(data) => Response::builder()
            .header(header::CONTENT_TYPE, "application/octet-stream")
            .header(
                header::CONTENT_DISPOSITION,
                format!("attachment; filename=\"{filename}\""),
            )
            .body(Body::from(data))
            .unwrap()
            .into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

// ---------------------------------------------------------------------------
// Station list pre-caching
// ---------------------------------------------------------------------------

async fn api_init() -> impl IntoResponse {
    match tokio::try_join!(
        stations::ensure_isd_station_list(),
        stations::ensure_igra_station_list(),
    ) {
        Ok(_) => Json(json!({"status": "ok"})).into_response(),
        Err(e) => {
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e}))).into_response()
        }
    }
}
