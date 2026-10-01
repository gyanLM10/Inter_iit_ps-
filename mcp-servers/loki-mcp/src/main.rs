use axum::{Router, routing::post};
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tracing_subscriber::{EnvFilter, fmt};

mod handlers;
mod sanitizer;

/// Shared application state holding the Loki base URL and HTTP client.
pub struct AppState {
    pub loki_url: String,
    pub http_client: reqwest::Client,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .json()
        .init();

    tracing::info!("Starting Loki-MCP server...");

    let loki_url = std::env::var("LOKI_URL")
        .unwrap_or_else(|_| "http://loki.monitoring.svc.cluster.local:3100".to_string());

    let state = Arc::new(AppState {
        loki_url,
        http_client: reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .build()?,
    });

    let app = Router::new()
        .route("/fetch_error_logs", post(handlers::fetch_error_logs))
        .route("/health", axum::routing::get(|| async { "OK" }))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = "0.0.0.0:3002";
    tracing::info!("Loki-MCP listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
