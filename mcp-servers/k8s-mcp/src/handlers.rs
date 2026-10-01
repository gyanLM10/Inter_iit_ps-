use axum::{Json, extract::State};
use k8s_openapi::api::apps::v1::{Deployment, ReplicaSet};
use k8s_openapi::api::core::v1::{Event, Pod};
use kube::{Api, api::ListParams};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use k8s_openapi::api::networking::v1::NetworkPolicy;

use crate::AppState;

// ─── Request / Response Types ────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct ListEventsRequest {
    pub namespace: String,
}

#[derive(Serialize)]
pub struct EventEntry {
    pub timestamp: Option<String>,
    pub reason: Option<String>,
    pub message: Option<String>,
    pub involved_object: String,
    pub event_type: Option<String>,
    pub count: Option<i32>,
}

#[derive(Serialize)]
pub struct ListEventsResponse {
    pub events: Vec<EventEntry>,
    pub namespace: String,
    pub total: usize,
}

#[derive(Deserialize)]
pub struct GetPodStatusRequest {
    pub pod_name: String,
    #[serde(default = "default_namespace")]
    pub namespace: String,
}

fn default_namespace() -> String {
    "workload".to_string()
}

#[derive(Serialize)]
pub struct ContainerStatusInfo {
    pub name: String,
    pub ready: bool,
    pub restart_count: i32,
    pub state: String,
    pub exit_code: Option<i32>,
    pub reason: Option<String>,
    pub last_termination_reason: Option<String>,
    pub last_termination_exit_code: Option<i32>,
}

#[derive(Serialize)]
pub struct PodStatusResponse {
    pub pod_name: String,
    pub namespace: String,
    pub phase: Option<String>,
    pub conditions: Vec<String>,
    pub containers: Vec<ContainerStatusInfo>,
    pub node_name: Option<String>,
    pub start_time: Option<String>,
}

#[derive(Deserialize)]
pub struct GetDeploymentDiffRequest {
    pub deployment_name: String,
    #[serde(default = "default_namespace")]
    pub namespace: String,
}

#[derive(Serialize)]
pub struct ReplicaSetInfo {
    pub name: String,
    pub revision: Option<String>,
    pub image: Option<String>,
    pub replicas: Option<i32>,
    pub ready_replicas: Option<i32>,
    pub created_at: Option<String>,
}

#[derive(Serialize)]
pub struct DeploymentDiffResponse {
    pub deployment_name: String,
    pub namespace: String,
    pub current: Option<ReplicaSetInfo>,
    pub previous: Option<ReplicaSetInfo>,
    pub diff_detected: bool,
    pub diff_summary: Vec<String>,
}

// ─── Handlers ────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct CheckNetworkPoliciesRequest {
    pub namespace: String,
}

#[derive(Serialize)]
pub struct CheckNetworkPoliciesResponse {
    pub namespace: String,
    pub policies: Vec<String>,
    pub total: usize,
}

/// List recent warning/error events in a namespace, sorted chronologically.
pub async fn list_recent_events(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ListEventsRequest>,
) -> Json<ListEventsResponse> {
    tracing::info!(namespace = %req.namespace, "Listing recent events");

    let events_api: Api<Event> = Api::namespaced(state.kube_client.clone(), &req.namespace);
    let lp = ListParams::default();

    let event_list = match events_api.list(&lp).await {
        Ok(list) => list,
        Err(e) => {
            tracing::error!(error = %e, "Failed to list events");
            return Json(ListEventsResponse {
                events: vec![],
                namespace: req.namespace,
                total: 0,
            });
        }
    };

    let mut entries: Vec<EventEntry> = event_list
        .items
        .into_iter()
        .filter(|e| {
            let event_type = e.type_.as_deref().unwrap_or("Normal");
            event_type == "Warning" || e.reason.as_deref().map_or(false, |r| {
                matches!(r, "Failed" | "FailedScheduling" | "Unhealthy" | "BackOff"
                    | "OOMKilling" | "Killing" | "FailedCreate" | "FailedMount"
                    | "NetworkNotReady" | "Evicted")
            })
        })
        .map(|e| {
            let involved = format!(
                "{}/{}",
                e.involved_object.kind.as_deref().unwrap_or("Unknown"),
                e.involved_object.name.as_deref().unwrap_or("unknown")
            );

            let timestamp = e
                .last_timestamp
                .as_ref()
                .map(|t| t.0.to_rfc3339())
                .or_else(|| {
                    e.metadata
                        .creation_timestamp
                        .as_ref()
                        .map(|t| t.0.to_rfc3339())
                });

            EventEntry {
                timestamp,
                reason: e.reason,
                message: e.message,
                involved_object: involved,
                event_type: e.type_,
                count: e.count,
            }
        })
        .collect();

    // Sort by timestamp (oldest first)
    entries.sort_by(|a, b| a.timestamp.cmp(&b.timestamp));

    let total = entries.len();
    // Return last 50 events max
    if entries.len() > 50 {
        entries = entries.split_off(entries.len() - 50);
    }

    Json(ListEventsResponse {
        events: entries,
        namespace: req.namespace,
        total,
    })
}

/// Get detailed pod status including container states, restart counts, and exit codes.
pub async fn get_pod_status(
    State(state): State<Arc<AppState>>,
    Json(req): Json<GetPodStatusRequest>,
) -> Json<serde_json::Value> {
    tracing::info!(pod = %req.pod_name, namespace = %req.namespace, "Getting pod status");

    let pods_api: Api<Pod> = Api::namespaced(state.kube_client.clone(), &req.namespace);

    // Try exact match first, then prefix match
    let pod = match pods_api.get(&req.pod_name).await {
        Ok(p) => p,
        Err(_) => {
            // Try listing pods with prefix match
            let lp = ListParams::default();
            match pods_api.list(&lp).await {
                Ok(list) => {
                    match list.items.into_iter().find(|p| {
                        p.metadata
                            .name
                            .as_deref()
                            .map_or(false, |n| n.starts_with(&req.pod_name))
                    }) {
                        Some(p) => p,
                        None => {
                            return Json(serde_json::json!({
                                "error": format!("Pod '{}' not found in namespace '{}'", req.pod_name, req.namespace)
                            }));
                        }
                    }
                }
                Err(e) => {
                    return Json(serde_json::json!({
                        "error": format!("Failed to list pods: {e}")
                    }));
                }
            }
        }
    };

    let status = pod.status.as_ref();
    let spec = pod.spec.as_ref();

    let phase = status.and_then(|s| s.phase.clone());

    let conditions: Vec<String> = status
        .and_then(|s| s.conditions.as_ref())
        .map(|conds| {
            conds
                .iter()
                .map(|c| format!("{}={}", c.type_, c.status))
                .collect()
        })
        .unwrap_or_default();

    let containers: Vec<ContainerStatusInfo> = status
        .and_then(|s| s.container_statuses.as_ref())
        .map(|statuses| {
            statuses
                .iter()
                .map(|cs| {
                    let (state_str, exit_code, reason) = if let Some(state) = &cs.state {
                        if let Some(running) = &state.running {
                            (
                                format!("Running (since {})", running.started_at.as_ref().map_or("unknown".to_string(), |t| t.0.to_rfc3339())),
                                None,
                                None,
                            )
                        } else if let Some(terminated) = &state.terminated {
                            (
                                "Terminated".to_string(),
                                Some(terminated.exit_code),
                                terminated.reason.clone(),
                            )
                        } else if let Some(waiting) = &state.waiting {
                            (
                                format!("Waiting: {}", waiting.reason.as_deref().unwrap_or("unknown")),
                                None,
                                waiting.reason.clone(),
                            )
                        } else {
                            ("Unknown".to_string(), None, None)
                        }
                    } else {
                        ("Unknown".to_string(), None, None)
                    };

                    let (last_reason, last_exit) = cs
                        .last_state
                        .as_ref()
                        .and_then(|ls| ls.terminated.as_ref())
                        .map(|t| (t.reason.clone(), Some(t.exit_code)))
                        .unwrap_or((None, None));

                    ContainerStatusInfo {
                        name: cs.name.clone(),
                        ready: cs.ready,
                        restart_count: cs.restart_count,
                        state: state_str,
                        exit_code,
                        reason,
                        last_termination_reason: last_reason,
                        last_termination_exit_code: last_exit,
                    }
                })
                .collect()
        })
        .unwrap_or_default();

    let node_name = spec.and_then(|s| s.node_name.clone());
    let start_time = status
        .and_then(|s| s.start_time.as_ref())
        .map(|t| t.0.to_rfc3339());

    let response = PodStatusResponse {
        pod_name: pod.metadata.name.unwrap_or_default(),
        namespace: req.namespace,
        phase,
        conditions,
        containers,
        node_name,
        start_time,
    };

    Json(serde_json::to_value(response).unwrap())
}

/// Compare current and previous ReplicaSets for a Deployment to detect config changes.
pub async fn get_deployment_diff(
    State(state): State<Arc<AppState>>,
    Json(req): Json<GetDeploymentDiffRequest>,
) -> Json<DeploymentDiffResponse> {
    tracing::info!(
        deployment = %req.deployment_name,
        namespace = %req.namespace,
        "Getting deployment diff"
    );

    let deploy_api: Api<Deployment> =
        Api::namespaced(state.kube_client.clone(), &req.namespace);
    let rs_api: Api<ReplicaSet> = Api::namespaced(state.kube_client.clone(), &req.namespace);

    // Get the deployment
    let deployment = match deploy_api.get(&req.deployment_name).await {
        Ok(d) => d,
        Err(e) => {
            tracing::error!(error = %e, "Failed to get deployment");
            return Json(DeploymentDiffResponse {
                deployment_name: req.deployment_name,
                namespace: req.namespace,
                current: None,
                previous: None,
                diff_detected: false,
                diff_summary: vec![format!("Error: {e}")],
            });
        }
    };

    // Get the deployment's selector to find its ReplicaSets
    let uid = deployment.metadata.uid.unwrap_or_default();
    let lp = ListParams::default();

    let rs_list = match rs_api.list(&lp).await {
        Ok(list) => list,
        Err(e) => {
            return Json(DeploymentDiffResponse {
                deployment_name: req.deployment_name,
                namespace: req.namespace,
                current: None,
                previous: None,
                diff_detected: false,
                diff_summary: vec![format!("Error listing ReplicaSets: {e}")],
            });
        }
    };

    // Filter ReplicaSets owned by this deployment
    let mut owned_rs: Vec<_> = rs_list
        .items
        .into_iter()
        .filter(|rs| {
            rs.metadata
                .owner_references
                .as_ref()
                .map_or(false, |refs| refs.iter().any(|r| r.uid == uid))
        })
        .collect();

    // Sort by revision annotation (descending)
    owned_rs.sort_by(|a, b| {
        let rev_a: i64 = a
            .metadata
            .annotations
            .as_ref()
            .and_then(|a| a.get("deployment.kubernetes.io/revision"))
            .and_then(|v| v.parse().ok())
            .unwrap_or(0);
        let rev_b: i64 = b
            .metadata
            .annotations
            .as_ref()
            .and_then(|a| a.get("deployment.kubernetes.io/revision"))
            .and_then(|v| v.parse().ok())
            .unwrap_or(0);
        rev_b.cmp(&rev_a)
    });

    let extract_info = |rs: &ReplicaSet| -> ReplicaSetInfo {
        let image = rs
            .spec
            .as_ref()
            .and_then(|s| s.template.as_ref())
            .and_then(|t| t.spec.as_ref())
            .and_then(|ps| ps.containers.first())
            .and_then(|c| c.image.clone());

        ReplicaSetInfo {
            name: rs.metadata.name.clone().unwrap_or_default(),
            revision: rs
                .metadata
                .annotations
                .as_ref()
                .and_then(|a| a.get("deployment.kubernetes.io/revision").cloned()),
            image,
            replicas: rs.spec.as_ref().and_then(|s| s.replicas),
            ready_replicas: rs.status.as_ref().and_then(|s| s.ready_replicas),
            created_at: rs
                .metadata
                .creation_timestamp
                .as_ref()
                .map(|t| t.0.to_rfc3339()),
        }
    };

    let current = owned_rs.first().map(extract_info);
    let previous = owned_rs.get(1).map(extract_info);

    // Compute diff
    let mut diff_summary = Vec::new();
    let diff_detected = if let (Some(curr), Some(prev)) = (&current, &previous) {
        if curr.image != prev.image {
            diff_summary.push(format!(
                "Image changed: {} -> {}",
                prev.image.as_deref().unwrap_or("unknown"),
                curr.image.as_deref().unwrap_or("unknown")
            ));
        }
        if curr.replicas != prev.replicas {
            diff_summary.push(format!(
                "Replicas changed: {:?} -> {:?}",
                prev.replicas, curr.replicas
            ));
        }
        !diff_summary.is_empty()
    } else {
        false
    };

    if diff_summary.is_empty() {
        diff_summary.push("No configuration changes detected between current and previous ReplicaSets".to_string());
    }

    Json(DeploymentDiffResponse {
        deployment_name: req.deployment_name,
        namespace: req.namespace,
        current,
        previous,
        diff_detected,
        diff_summary,
    })
}

/// Check network policies in a namespace.
pub async fn check_network_policies(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CheckNetworkPoliciesRequest>,
) -> Json<CheckNetworkPoliciesResponse> {
    tracing::info!(namespace = %req.namespace, "Checking network policies");

    let np_api: Api<NetworkPolicy> = Api::namespaced(state.kube_client.clone(), &req.namespace);
    let lp = ListParams::default();

    let np_list = match np_api.list(&lp).await {
        Ok(list) => list,
        Err(e) => {
            tracing::error!(error = %e, "Failed to list network policies");
            return Json(CheckNetworkPoliciesResponse {
                namespace: req.namespace,
                policies: vec![format!("Error listing policies: {e}")],
                total: 0,
            });
        }
    };

    let policies: Vec<String> = np_list
        .items
        .into_iter()
        .map(|np| {
            let name = np.metadata.name.unwrap_or_else(|| "unknown".to_string());
            let spec = np.spec.unwrap_or_default();
            let ingress = if spec.ingress.is_some() { "Ingress" } else { "" };
            let egress = if spec.egress.is_some() { "Egress" } else { "" };
            let policy_types = spec.policy_types.unwrap_or_default().join(",");
            format!("NetworkPolicy '{}' applies to {:?} ({}, {}) - Types: {}", name, spec.pod_selector.match_labels, ingress, egress, policy_types)
        })
        .collect();

    let total = policies.len();

    Json(CheckNetworkPoliciesResponse {
        namespace: req.namespace,
        policies,
        total,
    })
}
