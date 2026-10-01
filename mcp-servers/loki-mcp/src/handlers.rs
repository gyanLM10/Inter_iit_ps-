use axum::{Json, extract::State};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::AppState;
use crate::sanitizer::{self, LOG_END_DELIMITER, LOG_START_DELIMITER};

// ─── Request / Response Types ────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct FetchErrorLogsRequest {
    /// Pod name or pod name prefix
    pub pod_name: String,
    /// Time window like "5m", "15m", "1h"
    #[serde(default = "default_time_window")]
    pub time_window: String,
    /// Namespace
    #[serde(default = "default_namespace")]
    pub namespace: String,
}

fn default_time_window() -> String {
    "15m".to_string()
}

fn default_namespace() -> String {
    "workload".to_string()
}

#[derive(Serialize)]
pub struct SecurityMetadata {
    /// Number of lines flagged as containing potential prompt injection
    pub flagged_injection_count: usize,
    /// Details of flagged lines
    pub flagged_details: Vec<FlaggedDetail>,
    /// Whether the log data should be treated with extra caution
    pub contains_suspicious_content: bool,
}

#[derive(Serialize)]
pub struct FlaggedDetail {
    pub line_number: usize,
    pub pattern_type: String,
}

#[derive(Serialize)]
pub struct FetchErrorLogsResponse {
    pub pod_name: String,
    pub namespace: String,
    pub time_window: String,
    pub log_start_delimiter: String,
    pub logs: Vec<String>,
    pub log_end_delimiter: String,
    pub total_lines: usize,
    pub truncated_lines: usize,
    pub original_line_count: usize,
    pub security: SecurityMetadata,
    pub error: Option<String>,
}

// ─── Handler ─────────────────────────────────────────────────────────────────

pub async fn fetch_error_logs(
    State(state): State<Arc<AppState>>,
    Json(req): Json<FetchErrorLogsRequest>,
) -> Json<FetchErrorLogsResponse> {
    tracing::info!(
        pod = %req.pod_name,
        namespace = %req.namespace,
        time_window = %req.time_window,
        "Fetching error logs"
    );

    // Build LogQL query — filter for error/warning level logs
    let logql = format!(
        r#"{{namespace="{ns}",pod=~"{pod}.*"}} |~ "(?i)(error|err|fatal|panic|exception|fail|timeout|refused|oomkill|crash|traceback)""#,
        ns = req.namespace,
        pod = req.pod_name,
    );

    let url = format!(
        "{}/loki/api/v1/query_range?query={}&limit=500&since={}",
        state.loki_url,
        urlencoding::encode(&logql),
        urlencoding::encode(&req.time_window),
    );

    let raw_lines = match state.http_client.get(&url).send().await {
        Ok(resp) => {
            match resp.json::<serde_json::Value>().await {
                Ok(body) => extract_log_lines(&body),
                Err(e) => {
                    tracing::error!(error = %e, "Failed to parse Loki response");
                    return error_response(&req, format!("Failed to parse Loki response: {e}"));
                }
            }
        }
        Err(e) => {
            tracing::error!(error = %e, "Loki query failed");
            return error_response(&req, format!("Loki query failed: {e}"));
        }
    };

    // ═══════════════════════════════════════════════════════════════════════════
    // CRITICAL: Sanitize all log data before returning to the agent.
    // Logs are UNTRUSTED SENSOR DATA.
    // ═══════════════════════════════════════════════════════════════════════════
    let sanitized = sanitizer::sanitize_logs(raw_lines);

    let security = SecurityMetadata {
        flagged_injection_count: sanitized.flagged_lines.len(),
        flagged_details: sanitized
            .flagged_lines
            .iter()
            .map(|f| FlaggedDetail {
                line_number: f.line_number,
                pattern_type: f.pattern_matched.clone(),
            })
            .collect(),
        contains_suspicious_content: !sanitized.flagged_lines.is_empty(),
    };

    if security.contains_suspicious_content {
        tracing::warn!(
            flagged_count = security.flagged_injection_count,
            "⚠️  SECURITY: Potential prompt injection detected in log data from pod '{}'",
            req.pod_name
        );
    }

    let total_lines = sanitized.lines.len();

    Json(FetchErrorLogsResponse {
        pod_name: req.pod_name,
        namespace: req.namespace,
        time_window: req.time_window,
        log_start_delimiter: LOG_START_DELIMITER.to_string(),
        logs: sanitized.lines,
        log_end_delimiter: LOG_END_DELIMITER.to_string(),
        total_lines,
        truncated_lines: sanitized.truncated_count,
        original_line_count: sanitized.original_count,
        security,
        error: None,
    })
}

/// Extract individual log lines from Loki's query_range JSON response.
fn extract_log_lines(body: &serde_json::Value) -> Vec<String> {
    let mut lines = Vec::new();

    if let Some(results) = body["data"]["result"].as_array() {
        for stream in results {
            if let Some(values) = stream["values"].as_array() {
                for entry in values {
                    if let Some(arr) = entry.as_array() {
                        // Loki returns [timestamp_ns, log_line]
                        if let Some(log_line) = arr.get(1).and_then(|v| v.as_str()) {
                            lines.push(log_line.to_string());
                        }
                    }
                }
            }
        }
    }

    lines
}

fn error_response(req: &FetchErrorLogsRequest, error: String) -> Json<FetchErrorLogsResponse> {
    Json(FetchErrorLogsResponse {
        pod_name: req.pod_name.clone(),
        namespace: req.namespace.clone(),
        time_window: req.time_window.clone(),
        log_start_delimiter: LOG_START_DELIMITER.to_string(),
        logs: vec![],
        log_end_delimiter: LOG_END_DELIMITER.to_string(),
        total_lines: 0,
        truncated_lines: 0,
        original_line_count: 0,
        security: SecurityMetadata {
            flagged_injection_count: 0,
            flagged_details: vec![],
            contains_suspicious_content: false,
        },
        error: Some(error),
    })
}
