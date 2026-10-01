use axum::{Router, routing::post};
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tracing_subscriber::{EnvFilter, fmt};

mod handlers;

/// Shared application state holding the Prometheus base URL and HTTP client.
pub struct AppState {
    pub prometheus_url: String,
    pub http_client: reqwest::Client,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .json()
        .init();

    tracing::info!("Starting Prometheus-MCP server...");

    let prometheus_url = std::env::var("PROMETHEUS_URL")
        .unwrap_or_else(|_| "http://prometheus-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090".to_string());

    let state = Arc::new(AppState {
        prometheus_url,
        http_client: reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()?,
    });

    let app = Router::new()
        .route("/query_anomaly", post(handlers::query_anomaly))
        .route("/health", axum::routing::get(|| async { "OK" }))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = "0.0.0.0:3001";
    tracing::info!("Prometheus-MCP listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
