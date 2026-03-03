/// AERMET control file generation and execution.
///
/// Generates control files for all 3 AERMET stages and runs aermet.exe.
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn aermet_exe() -> Option<PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));
    let exe = exe_dir.join("bin").join("aermet.exe");
    if exe.exists() {
        return Some(exe);
    }
    let exe2 = exe_dir.join("bin").join("aermet");
    if exe2.exists() {
        return Some(exe2);
    }
    None
}

// ---------------------------------------------------------------------------
// Control file generation
// ---------------------------------------------------------------------------

pub fn generate_stage1(
    work_dir: &Path,
    year: i32,
    surface_file: &str,
    upper_air_file: &str,
    sf_station_id: &str,
    sf_lat: f64,
    sf_lon: f64,
    ua_station_id: &str,
    ua_lat: f64,
    ua_lon: f64,
    onemin_file: Option<&str>,
) -> Result<PathBuf, String> {
    let prefix = format!("s1_{year}");
    let ctrl_path = work_dir.join(format!("{prefix}.inp"));
    let start_date = format!("{year}/01/01");
    let end_date = format!("{year}/12/31");

    let oneminute_line = onemin_file
        .map(|f| format!("   ONEMINUTE   {f}"))
        .unwrap_or_default();

    let ctrl = format!(
        "JOB\n\
         \x20  MESSAGES   {prefix}.msg\n\
         \x20  REPORT     {prefix}.rpt\n\
         \n\
         UPPERAIR\n\
         \x20  DATA       {upper_air_file}  IGRA\n\
         \x20  EXTRACT    {prefix}_ua.ext\n\
         \x20  AUDIT      UATT UAWS UALR\n\
         \x20  QAOUT      {prefix}_ua.qa\n\
         \x20  XDATES     {start_date}  TO  {end_date}\n\
         \x20  LOCATION   {ua_station_id}  {ua_lat:.4}  {ua_lon:.4}\n\
         \n\
         SURFACE\n\
         \x20  DATA       {surface_file}  ISHD\n\
         \x20  EXTRACT    {prefix}_sf.ext\n\
         \x20  AUDIT      SLVP PRES CLHT TSKC PWTH APTS\n\
         \x20  QAOUT      {prefix}_sf.qa\n\
         \x20  XDATES     {start_date}  TO  {end_date}\n\
         \x20  LOCATION   {sf_station_id}  {sf_lat:.4}  {sf_lon:.4}\n\
         {oneminute_line}\n"
    );

    fs::write(&ctrl_path, ctrl).map_err(|e| format!("Write stage1: {e}"))?;
    Ok(ctrl_path)
}

pub fn generate_stage2(
    work_dir: &Path,
    year: i32,
    onemin_file: Option<&str>,
) -> Result<PathBuf, String> {
    let prefix = format!("s2_{year}");
    let s1_prefix = format!("s1_{year}");
    let ctrl_path = work_dir.join(format!("{prefix}.inp"));

    let oneminute_line = onemin_file
        .map(|f| format!("   ONEMINUTE   {f}"))
        .unwrap_or_default();

    let ctrl = format!(
        "JOB\n\
         \x20  MESSAGES   {prefix}.msg\n\
         \x20  REPORT     {prefix}.rpt\n\
         \n\
         UPPERAIR\n\
         \x20  QAOUT      {s1_prefix}_ua.qa\n\
         \n\
         SURFACE\n\
         \x20  QAOUT      {s1_prefix}_sf.qa\n\
         {oneminute_line}\n\
         \n\
         MERGE\n\
         \x20  OUTPUT     {prefix}_merge.out\n\
         \x20  XDATES     {year}/01/01  TO  {year}/12/31\n"
    );

    fs::write(&ctrl_path, ctrl).map_err(|e| format!("Write stage2: {e}"))?;
    Ok(ctrl_path)
}

#[derive(Debug, Clone, Serialize, serde::Deserialize)]
pub struct ManualSurfaceChars {
    pub albedo: f64,
    pub bowen: f64,
    pub roughness: f64,
}

pub fn generate_stage3(
    work_dir: &Path,
    year: i32,
    sf_station_id: &str,
    sf_lat: f64,
    sf_lon: f64,
    ua_station_id: &str,
    ua_lat: f64,
    ua_lon: f64,
    aersurface_file: Option<&str>,
    anemometer_height: f64,
    manual_surface_chars: Option<&ManualSurfaceChars>,
) -> Result<PathBuf, String> {
    let prefix = format!("s3_{year}");
    let s2_prefix = format!("s2_{year}");
    let ctrl_path = work_dir.join(format!("{prefix}.inp"));
    let sfc_out = format!("output/{year}.SFC");
    let pfl_out = format!("output/{year}.PFL");

    let surf_chars = if let Some(asf) = aersurface_file {
        format!("   AERSURF    {asf}")
    } else if let Some(mc) = manual_surface_chars {
        format!(
            "   FREQ_SECT  ANNUAL  1\n\
             \x20  SECTOR     1   0  360\n\
             \x20  SITE_CHAR  1  1  {}  {}  {}\n\
             \x20  SITE_CHAR  1  2  {}  {}  {}\n\
             \x20  SITE_CHAR  1  3  {}  {}  {}\n\
             \x20  SITE_CHAR  1  4  {}  {}  {}",
            mc.albedo, mc.bowen, mc.roughness,
            mc.albedo, mc.bowen, mc.roughness,
            mc.albedo, mc.bowen, mc.roughness,
            mc.albedo, mc.bowen, mc.roughness,
        )
    } else {
        "   FREQ_SECT  ANNUAL  1\n\
         \x20  SECTOR     1   0  360\n\
         \x20  SITE_CHAR  1  1  0.18  1.0  0.15\n\
         \x20  SITE_CHAR  1  2  0.18  1.0  0.15\n\
         \x20  SITE_CHAR  1  3  0.18  1.0  0.15\n\
         \x20  SITE_CHAR  1  4  0.18  1.0  0.15"
            .to_string()
    };

    let ctrl = format!(
        "JOB\n\
         \x20  MESSAGES   {prefix}.msg\n\
         \x20  REPORT     {prefix}.rpt\n\
         \n\
         METPREP\n\
         \x20  DATA       {s2_prefix}_merge.out\n\
         \x20  XDATES     {year}/01/01  TO  {year}/12/31\n\
         \x20  OUTPUT     {sfc_out}\n\
         \x20  PROFILE    {pfl_out}\n\
         \x20  SURFDATA   {sf_station_id}  {year}\n\
         \x20  UAIRDATA   {ua_station_id}  {year}\n\
         \x20  SURFLOCN   {sf_lat:.4}  {sf_lon:.4}\n\
         \x20  UAIRLOCN   {ua_lat:.4}  {ua_lon:.4}\n\
         \x20  NWS_HGT    {anemometer_height}\n\
         \x20  METHOD     REFLEVEL  SUBNWS\n\
         {surf_chars}\n"
    );

    fs::write(&ctrl_path, ctrl).map_err(|e| format!("Write stage3: {e}"))?;
    Ok(ctrl_path)
}

// ---------------------------------------------------------------------------
// Execution
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct AermetResult {
    pub success: bool,
    pub return_code: i32,
    #[serde(default)]
    pub messages: Vec<String>,
    #[serde(default)]
    pub warnings: Vec<String>,
    #[serde(default)]
    pub errors: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

pub fn run_aermet(
    ctrl_path: &Path,
    work_dir: &Path,
    progress_cb: &dyn Fn(&str, &str),
) -> AermetResult {
    let exe = match aermet_exe() {
        Some(e) => e,
        None => {
            return AermetResult {
                success: false,
                return_code: -1,
                messages: vec![],
                warnings: vec![],
                errors: vec!["AERMET executable not found".to_string()],
                error: Some(
                    "AERMET executable not found. Place aermet.exe in bin/".to_string(),
                ),
            }
        }
    };

    let ctrl_filename = ctrl_path
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();

    progress_cb("running", &format!("Running AERMET with {ctrl_filename}..."));

    let result = Command::new(&exe)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .current_dir(work_dir)
        .spawn()
        .and_then(|mut child| {
            use std::io::Write;
            if let Some(ref mut stdin) = child.stdin {
                let _ = write!(stdin, "{ctrl_filename}\n");
            }
            child.wait_with_output()
        });

    match result {
        Ok(output) => {
            let msg_file = ctrl_filename.replace(".inp", ".msg");
            let msg_path = work_dir.join(&msg_file);
            let (messages, warnings, errors) = parse_message_file(&msg_path);

            let success = output.status.success() && errors.is_empty();
            let status = if success { "done" } else { "error" };
            let msg = if success { "OK" } else { "errors found" };
            progress_cb(status, &format!("AERMET {ctrl_filename}: {msg}"));

            AermetResult {
                success,
                return_code: output.status.code().unwrap_or(-1),
                messages,
                warnings,
                errors,
                error: None,
            }
        }
        Err(e) => AermetResult {
            success: false,
            return_code: -1,
            messages: vec![],
            warnings: vec![],
            errors: vec![format!("Failed to run AERMET: {e}")],
            error: Some(format!("Failed to run AERMET: {e}")),
        },
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct StageResults {
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stage: Option<i32>,
    pub sfc_path: String,
    pub pfl_path: String,
    pub results: serde_json::Value,
}

pub fn run_aermet_all_stages(
    work_dir: &Path,
    year: i32,
    surface_file: &str,
    upper_air_file: &str,
    sf_station_id: &str,
    sf_lat: f64,
    sf_lon: f64,
    ua_station_id: &str,
    ua_lat: f64,
    ua_lon: f64,
    aersurface_file: Option<&str>,
    onemin_file: Option<&str>,
    anemometer_height: f64,
    manual_surface_chars: Option<&ManualSurfaceChars>,
    progress_cb: &dyn Fn(&str, &str),
) -> StageResults {
    let mut results = serde_json::Map::new();

    // Stage 1
    progress_cb("stage1", &format!("AERMET Stage 1 ({year}): Extract & QA..."));
    let ctrl1 = match generate_stage1(
        work_dir,
        year,
        surface_file,
        upper_air_file,
        sf_station_id,
        sf_lat,
        sf_lon,
        ua_station_id,
        ua_lat,
        ua_lon,
        onemin_file,
    ) {
        Ok(p) => p,
        Err(e) => {
            return StageResults {
                success: false,
                stage: Some(1),
                sfc_path: String::new(),
                pfl_path: String::new(),
                results: serde_json::json!({"error": e}),
            }
        }
    };

    let r1 = run_aermet(&ctrl1, work_dir, progress_cb);
    results.insert(
        "stage1".to_string(),
        serde_json::to_value(&r1).unwrap_or_default(),
    );
    if !r1.success {
        return StageResults {
            success: false,
            stage: Some(1),
            sfc_path: String::new(),
            pfl_path: String::new(),
            results: serde_json::Value::Object(results),
        };
    }

    // Stage 2
    progress_cb("stage2", &format!("AERMET Stage 2 ({year}): Merge..."));
    let ctrl2 = match generate_stage2(work_dir, year, onemin_file) {
        Ok(p) => p,
        Err(e) => {
            return StageResults {
                success: false,
                stage: Some(2),
                sfc_path: String::new(),
                pfl_path: String::new(),
                results: serde_json::json!({"error": e}),
            }
        }
    };

    let r2 = run_aermet(&ctrl2, work_dir, progress_cb);
    results.insert(
        "stage2".to_string(),
        serde_json::to_value(&r2).unwrap_or_default(),
    );
    if !r2.success {
        return StageResults {
            success: false,
            stage: Some(2),
            sfc_path: String::new(),
            pfl_path: String::new(),
            results: serde_json::Value::Object(results),
        };
    }

    // Stage 3
    progress_cb("stage3", &format!("AERMET Stage 3 ({year}): METPREP..."));
    let ctrl3 = match generate_stage3(
        work_dir,
        year,
        sf_station_id,
        sf_lat,
        sf_lon,
        ua_station_id,
        ua_lat,
        ua_lon,
        aersurface_file,
        anemometer_height,
        manual_surface_chars,
    ) {
        Ok(p) => p,
        Err(e) => {
            return StageResults {
                success: false,
                stage: Some(3),
                sfc_path: String::new(),
                pfl_path: String::new(),
                results: serde_json::json!({"error": e}),
            }
        }
    };

    let r3 = run_aermet(&ctrl3, work_dir, progress_cb);
    results.insert(
        "stage3".to_string(),
        serde_json::to_value(&r3).unwrap_or_default(),
    );

    let sfc_path = work_dir.join("output").join(format!("{year}.SFC"));
    let pfl_path = work_dir.join("output").join(format!("{year}.PFL"));

    StageResults {
        success: r3.success,
        stage: None,
        sfc_path: sfc_path.to_string_lossy().to_string(),
        pfl_path: pfl_path.to_string_lossy().to_string(),
        results: serde_json::Value::Object(results),
    }
}

// ---------------------------------------------------------------------------
// Message file parsing
// ---------------------------------------------------------------------------

fn parse_message_file(msg_path: &Path) -> (Vec<String>, Vec<String>, Vec<String>) {
    let mut messages = Vec::new();
    let mut warnings = Vec::new();
    let mut errors = Vec::new();

    if !msg_path.exists() {
        return (messages, warnings, errors);
    }

    let text = match fs::read_to_string(msg_path) {
        Ok(t) => t,
        Err(_) => return (messages, warnings, errors),
    };

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let upper = line.to_uppercase();
        if line.contains("***") && upper.contains("ERROR") {
            errors.push(line.to_string());
        } else if line.contains("***") && upper.contains("WARNING") {
            warnings.push(line.to_string());
        } else if line.starts_with("***") {
            messages.push(line.to_string());
        } else if line.starts_with("E ") || line.starts_with("E\t") {
            errors.push(line.to_string());
        } else if line.starts_with("W ") || line.starts_with("W\t") {
            warnings.push(line.to_string());
        }
    }

    (messages, warnings, errors)
}

/// Combine multiple per-year .SFC files into one.
pub fn combine_sfc_files(sfc_files: &[String], output_path: &Path) -> Result<(), String> {
    let mut out = fs::File::create(output_path).map_err(|e| format!("Create: {e}"))?;
    let mut sorted = sfc_files.to_vec();
    sorted.sort();
    for path in &sorted {
        let data = fs::read_to_string(path).map_err(|e| format!("Read {path}: {e}"))?;
        use std::io::Write;
        write!(out, "{data}").map_err(|e| format!("Write: {e}"))?;
    }
    Ok(())
}

/// Combine multiple per-year .PFL files into one.
pub fn combine_pfl_files(pfl_files: &[String], output_path: &Path) -> Result<(), String> {
    let mut out = fs::File::create(output_path).map_err(|e| format!("Create: {e}"))?;
    let mut sorted = pfl_files.to_vec();
    sorted.sort();
    for path in &sorted {
        let data = fs::read_to_string(path).map_err(|e| format!("Read {path}: {e}"))?;
        use std::io::Write;
        write!(out, "{data}").map_err(|e| format!("Write: {e}"))?;
    }
    Ok(())
}
