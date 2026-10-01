use axum::{Router, routing::post};
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tracing_subscriber::{EnvFilter, fmt};

mod handlers;

/// Shared application state holding the Kubernetes client.
pub struct AppState {
    pub kube_client: kube::Client,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize structured logging
    fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .json()
        .init();

    tracing::info!("Starting K8s-MCP server...");

    // Initialize Kubernetes client (uses in-cluster config or KUBECONFIG)
    let client = kube::Client::try_default().await?;
    tracing::info!("Kubernetes client initialized");

    let state = Arc::new(AppState {
        kube_client: client,
    });

    let app = Router::new()
        .route("/list_recent_events", post(handlers::list_recent_events))
        .route("/get_pod_status", post(handlers::get_pod_status))
        .route("/get_deployment_diff", post(handlers::get_deployment_diff))
        .route("/check_network_policies", post(handlers::check_network_policies))
        .route("/health", axum::routing::get(|| async { "OK" }))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = "0.0.0.0:3000";
    tracing::info!("K8s-MCP listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
