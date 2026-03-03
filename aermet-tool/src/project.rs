/// Project state management — tracks configuration and progress of an AERMET run.
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use uuid::Uuid;

/// Base directory for all projects (resolved at runtime relative to exe).
fn projects_dir() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));
    exe_dir.join("projects")
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Location {
    pub lat: f64,
    pub lon: f64,
    #[serde(default)]
    pub display_name: String,
    #[serde(default)]
    pub country_code: String,
    #[serde(default)]
    pub is_us: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataPeriod {
    pub start_year: i32,
    pub end_year: i32,
    pub num_years: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Completeness {
    pub threshold: f64,
    pub basis: String, // "quarterly" or "annual"
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: String,
    pub dir: String,
    pub created: f64,
    pub location: Location,
    pub data_period: DataPeriod,
    pub completeness: Completeness,
    pub is_us: bool,
    pub surface_station: Option<serde_json::Value>,
    pub upper_air_station: Option<serde_json::Value>,
    pub status: String,
    #[serde(default)]
    pub steps_completed: Vec<String>,
    #[serde(default)]
    pub errors: Vec<String>,
    #[serde(default)]
    pub results: serde_json::Value,
}

#[derive(Debug, Deserialize)]
pub struct CreateProjectRequest {
    pub location: Location,
    pub data_period: CreateDataPeriod,
    pub completeness: Completeness,
    #[serde(default = "default_true")]
    pub is_us: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Deserialize)]
pub struct CreateDataPeriod {
    pub start_year: i32,
    pub num_years: i32,
}

pub fn create_project(req: CreateProjectRequest) -> Result<Project, String> {
    let project_id = Uuid::new_v4().to_string()[..8].to_string();
    let project_dir = projects_dir().join(&project_id);

    for sub in &["surface", "upper_air", "one_minute", "aermet", "output"] {
        fs::create_dir_all(project_dir.join(sub))
            .map_err(|e| format!("Failed to create directory: {e}"))?;
    }

    let end_year = req.data_period.start_year + req.data_period.num_years - 1;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();

    let project = Project {
        id: project_id,
        dir: project_dir.to_string_lossy().to_string(),
        created: now,
        location: req.location,
        data_period: DataPeriod {
            start_year: req.data_period.start_year,
            end_year,
            num_years: req.data_period.num_years,
        },
        completeness: req.completeness,
        is_us: req.is_us,
        surface_station: None,
        upper_air_station: None,
        status: "created".to_string(),
        steps_completed: vec![],
        errors: vec![],
        results: serde_json::Value::Object(serde_json::Map::new()),
    };

    save_project(&project)?;
    Ok(project)
}

pub fn load_project(project_id: &str) -> Result<Project, String> {
    let path = projects_dir().join(project_id).join("project.json");
    if !path.exists() {
        return Err(format!("Project {project_id} not found"));
    }
    let data = fs::read_to_string(&path).map_err(|e| format!("Read error: {e}"))?;
    serde_json::from_str(&data).map_err(|e| format!("Parse error: {e}"))
}

pub fn update_project(project: &mut Project, updates: serde_json::Value) -> Result<(), String> {
    if let serde_json::Value::Object(map) = updates {
        for (key, val) in map {
            match key.as_str() {
                "status" => {
                    if let Some(s) = val.as_str() {
                        project.status = s.to_string();
                    }
                }
                "surface_station" => project.surface_station = Some(val),
                "upper_air_station" => project.upper_air_station = Some(val),
                "results" => project.results = val,
                "errors" => {
                    if let Ok(e) = serde_json::from_value(val) {
                        project.errors = e;
                    }
                }
                _ => {}
            }
        }
    }
    save_project(project)
}

pub fn save_project(project: &Project) -> Result<(), String> {
    let path = Path::new(&project.dir).join("project.json");
    let data = serde_json::to_string_pretty(project).map_err(|e| format!("Serialize: {e}"))?;
    fs::write(&path, data).map_err(|e| format!("Write error: {e}"))
}
