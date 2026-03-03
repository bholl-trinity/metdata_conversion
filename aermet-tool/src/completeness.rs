/// SFC file completeness assessment.
///
/// Parses AERMET .SFC output files to determine what percentage of hours
/// have valid meteorological data.
use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

const MISSING_VALUE: f64 = -999.0;

#[derive(Debug, Clone, Serialize)]
pub struct CompletenessResult {
    pub total_hours: i32,
    pub valid_hours: i32,
    pub missing_hours: i32,
    pub completeness_pct: f64,
    pub by_quarter: HashMap<String, f64>,
    pub by_month: HashMap<String, f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CheckResult {
    pub passes: bool,
    pub completeness: CompletenessResult,
    pub failures: Vec<String>,
}

struct SfcRecord {
    month: i32,
    h0: f64,
    ustar: f64,
}

fn is_leap_year(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn days_in_month(year: i32, month: i32) -> i32 {
    match month {
        1 => 31,
        2 => {
            if is_leap_year(year) {
                29
            } else {
                28
            }
        }
        3 => 31,
        4 => 30,
        5 => 31,
        6 => 30,
        7 => 31,
        8 => 31,
        9 => 30,
        10 => 31,
        11 => 30,
        12 => 31,
        _ => 30,
    }
}

fn parse_sfc_file(sfc_path: &Path) -> Vec<SfcRecord> {
    let mut records = Vec::new();
    let text = match fs::read_to_string(sfc_path) {
        Ok(t) => t,
        Err(_) => return records,
    };

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 16 {
            continue;
        }

        let mo: i32 = match parts[1].parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let h0: f64 = match parts[5].parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        let ustar: f64 = match parts[6].parse() {
            Ok(v) => v,
            Err(_) => continue,
        };

        records.push(SfcRecord {
            month: mo,
            h0,
            ustar,
        });
    }
    records
}

fn is_hour_valid(rec: &SfcRecord) -> bool {
    // H0 (sensible heat flux) must not be missing
    if rec.h0 <= MISSING_VALUE + 1.0 {
        return false;
    }
    // Friction velocity must not be missing
    if rec.ustar <= MISSING_VALUE + 1.0 {
        return false;
    }
    // Calm winds are valid
    true
}

pub fn compute_completeness(sfc_path: &Path, full_year: Option<i32>) -> CompletenessResult {
    let records = parse_sfc_file(sfc_path);

    let year = full_year.unwrap_or(2020);
    let total_hours = if is_leap_year(year) { 8784 } else { 8760 };

    if records.is_empty() {
        let by_quarter: HashMap<String, f64> = (1..=4)
            .map(|q| (format!("Q{q}"), 0.0))
            .collect();
        let by_month: HashMap<String, f64> = (1..=12)
            .map(|m| (m.to_string(), 0.0))
            .collect();
        return CompletenessResult {
            total_hours,
            valid_hours: 0,
            missing_hours: total_hours,
            completeness_pct: 0.0,
            by_quarter,
            by_month,
        };
    }

    // Expected hours per month
    let mut expected_by_month: HashMap<i32, i32> = HashMap::new();
    for m in 1..=12 {
        expected_by_month.insert(m, days_in_month(year, m) * 24);
    }

    let mut valid_total = 0;
    let mut valid_by_month: HashMap<i32, i32> = (1..=12).map(|m| (m, 0)).collect();

    for rec in &records {
        if (1..=12).contains(&rec.month) && is_hour_valid(rec) {
            valid_total += 1;
            *valid_by_month.entry(rec.month).or_insert(0) += 1;
        }
    }

    // Monthly completeness
    let by_month: HashMap<String, f64> = (1..=12)
        .map(|m| {
            let expected = expected_by_month[&m] as f64;
            let valid = valid_by_month[&m] as f64;
            let pct = if expected > 0.0 {
                (valid / expected * 1000.0).round() / 10.0
            } else {
                0.0
            };
            (m.to_string(), pct)
        })
        .collect();

    // Quarterly completeness
    let quarters: [(String, &[i32]); 4] = [
        ("Q1".to_string(), &[1, 2, 3]),
        ("Q2".to_string(), &[4, 5, 6]),
        ("Q3".to_string(), &[7, 8, 9]),
        ("Q4".to_string(), &[10, 11, 12]),
    ];

    let by_quarter: HashMap<String, f64> = quarters
        .iter()
        .map(|(qname, months)| {
            let q_expected: i32 = months.iter().map(|m| expected_by_month[m]).sum();
            let q_valid: i32 = months.iter().map(|m| valid_by_month[m]).sum();
            let pct = if q_expected > 0 {
                (q_valid as f64 / q_expected as f64 * 1000.0).round() / 10.0
            } else {
                0.0
            };
            (qname.clone(), pct)
        })
        .collect();

    let completeness_pct = if total_hours > 0 {
        (valid_total as f64 / total_hours as f64 * 1000.0).round() / 10.0
    } else {
        0.0
    };

    CompletenessResult {
        total_hours,
        valid_hours: valid_total,
        missing_hours: total_hours - valid_total,
        completeness_pct,
        by_quarter,
        by_month,
    }
}

pub fn check_completeness(
    sfc_path: &Path,
    threshold: f64,
    basis: &str,
    full_year: Option<i32>,
) -> CheckResult {
    let comp = compute_completeness(sfc_path, full_year);
    let mut failures = Vec::new();

    if basis == "quarterly" {
        for (qname, pct) in &comp.by_quarter {
            if *pct < threshold {
                failures.push(format!("{qname}: {pct}% (threshold: {threshold}%)"));
            }
        }
    } else if comp.completeness_pct < threshold {
        failures.push(format!(
            "Annual: {}% (threshold: {threshold}%)",
            comp.completeness_pct
        ));
    }

    CheckResult {
        passes: failures.is_empty(),
        completeness: comp,
        failures,
    }
}
