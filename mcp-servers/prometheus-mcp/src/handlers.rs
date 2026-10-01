use axum::{Json, extract::State};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::AppState;

// ─── Request / Response Types ────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct QueryAnomalyRequest {
    /// One of: check_cpu_saturation, check_5xx_rate, check_db_connections, check_memory_usage
    pub metric_type: String,
    /// Pod name, deployment name, or service name to filter on
    pub resource_name: String,
    #[serde(default = "default_namespace")]
    pub namespace: String,
}

fn default_namespace() -> String {
    "workload".to_string()
}

#[derive(Serialize)]
pub struct MetricResult {
    pub metric_labels: serde_json::Value,
    pub value: String,
    pub timestamp: f64,
}

#[derive(Serialize)]
pub struct QueryAnomalyResponse {
    pub metric_type: String,
    pub resource_name: String,
    pub query_used: String,
    pub results: Vec<MetricResult>,
    pub summary: String,
    pub error: Option<String>,
}

// ─── Pre-built PromQL Templates ──────────────────────────────────────────────

/// Returns a pre-built PromQL query for the given metric type.
/// This prevents the LLM from hallucinating PromQL syntax.
fn build_promql(metric_type: &str, resource_name: &str, namespace: &str) -> Option<String> {
    match metric_type {
        "check_cpu_saturation" => Some(format!(
            r#"sum(rate(container_cpu_usage_seconds_total{{namespace=~"{namespace}",pod=~".*{resource_name}.*"}}[5m])) by (pod) / sum(kube_pod_container_resource_limits{{namespace=~"{namespace}",pod=~".*{resource_name}.*",resource="cpu"}}) by (pod) * 100"#
        )),

        "check_5xx_rate" => Some(format!(
            r#"sum(rate(http_requests_total{{namespace=~"{namespace}",pod=~".*{resource_name}.*",status=~"5.."}}[5m])) by (pod) or sum(rate(http_server_requests_seconds_count{{namespace=~"{namespace}",pod=~".*{resource_name}.*",status=~"5.."}}[5m])) by (pod)"#
        )),

        "check_db_connections" => Some(format!(
            r#"pg_stat_activity_count{{namespace=~"{namespace}",pod=~".*{resource_name}.*"}} or pg_stat_activity_count{{kubernetes_namespace=~"{namespace}",pod=~".*{resource_name}.*"}}"#
        )),

        "check_memory_usage" => Some(format!(
            r#"sum(container_memory_working_set_bytes{{namespace=~"{namespace}",pod=~".*{resource_name}.*",container!="",container!="POD"}}) by (pod) / sum(kube_pod_container_resource_limits{{namespace=~"{namespace}",pod=~".*{resource_name}.*",resource="memory"}}) by (pod) * 100"#
        )),

        _ => None,
    }
}

/// Summarize the metric results in plain English.
fn summarize_results(metric_type: &str, results: &[MetricResult]) -> String {
    if results.is_empty() {
        return format!("No data available for metric '{metric_type}'. The metric may not be emitted by the target workload.");
    }

    let values: Vec<f64> = results
        .iter()
        .filter_map(|r| r.value.parse::<f64>().ok())
        .collect();

    if values.is_empty() {
        return "All returned values are non-numeric or NaN.".to_string();
    }

    let max = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let min = values.iter().cloned().fold(f64::INFINITY, f64::min);
    let avg = values.iter().sum::<f64>() / values.len() as f64;

    match metric_type {
        "check_cpu_saturation" => {
            if max > 90.0 {
                format!("CRITICAL: CPU saturation at {max:.1}% (avg: {avg:.1}%). Resource starvation likely.")
            } else if max > 70.0 {
                format!("WARNING: CPU saturation at {max:.1}% (avg: {avg:.1}%). Approaching limits.")
            } else {
                format!("NORMAL: CPU saturation at {max:.1}% (avg: {avg:.1}%). Within healthy range.")
            }
        }
        "check_5xx_rate" => {
            if max > 0.0 {
                format!("ALERT: 5xx error rate detected. Max rate: {max:.4} req/s across {len} pod(s).", len = results.len())
            } else {
                "NORMAL: No 5xx errors detected.".to_string()
            }
        }
        "check_db_connections" => {
            format!("Database connections: min={min:.0}, max={max:.0}, avg={avg:.1} across {len} target(s).", len = results.len())
        }
        "check_memory_usage" => {
            if max > 90.0 {
                format!("CRITICAL: Memory usage at {max:.1}% of limit (avg: {avg:.1}%). OOMKill risk is HIGH.")
            } else if max > 75.0 {
                format!("WARNING: Memory usage at {max:.1}% of limit (avg: {avg:.1}%). Elevated risk.")
            } else {
                format!("NORMAL: Memory usage at {max:.1}% of limit (avg: {avg:.1}%). Within healthy range.")
            }
        }
        _ => format!("Results: {len} series returned. Max: {max:.4}, Min: {min:.4}, Avg: {avg:.4}", len = results.len()),
    }
}

// ─── Handler ─────────────────────────────────────────────────────────────────

pub async fn query_anomaly(
    State(state): State<Arc<AppState>>,
    Json(req): Json<QueryAnomalyRequest>,
) -> Json<QueryAnomalyResponse> {
    tracing::info!(
        metric_type = %req.metric_type,
        resource = %req.resource_name,
        namespace = %req.namespace,
        "Querying anomaly"
    );

    let query = match build_promql(&req.metric_type, &req.resource_name, &req.namespace) {
        Some(q) => q,
        None => {
            return Json(QueryAnomalyResponse {
                metric_type: req.metric_type.clone(),
                resource_name: req.resource_name,
                query_used: String::new(),
                results: vec![],
                summary: String::new(),
                error: Some(format!(
                    "Unknown metric_type '{}'. Valid options: check_cpu_saturation, check_5xx_rate, check_db_connections, check_memory_usage",
                    req.metric_type
                )),
            });
        }
    };

    // Query Prometheus instant query API
    let url = format!(
        "{}/api/v1/query?query={}",
        state.prometheus_url,
        urlencoding::encode(&query)
    );

    let response = match state.http_client.get(&url).send().await {
        Ok(resp) => resp,
        Err(e) => {
            tracing::error!(error = %e, "Prometheus query failed");
            return Json(QueryAnomalyResponse {
                metric_type: req.metric_type,
                resource_name: req.resource_name,
                query_used: query,
                results: vec![],
                summary: String::new(),
                error: Some(format!("Prometheus query failed: {e}")),
            });
        }
    };

    let body: serde_json::Value = match response.json().await {
        Ok(v) => v,
        Err(e) => {
            return Json(QueryAnomalyResponse {
                metric_type: req.metric_type,
                resource_name: req.resource_name,
                query_used: query,
                results: vec![],
                summary: String::new(),
                error: Some(format!("Failed to parse Prometheus response: {e}")),
            });
        }
    };

    // Parse results from Prometheus response
    let results: Vec<MetricResult> = body["data"]["result"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|item| {
                    let metric_labels = item["metric"].clone();
                    let value_arr = item["value"].as_array()?;
                    let timestamp = value_arr.first()?.as_f64()?;
                    let value = value_arr.get(1)?.as_str()?.to_string();
                    Some(MetricResult {
                        metric_labels,
                        value,
                        timestamp,
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let summary = summarize_results(&req.metric_type, &results);

    Json(QueryAnomalyResponse {
        metric_type: req.metric_type,
        resource_name: req.resource_name,
        query_used: query,
        results,
        summary,
        error: None,
    })
}
