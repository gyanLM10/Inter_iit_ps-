FROM rust:slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml ./
COPY loki-mcp/ loki-mcp/
COPY k8s-mcp/Cargo.toml k8s-mcp/Cargo.toml
COPY prometheus-mcp/Cargo.toml prometheus-mcp/Cargo.toml
RUN mkdir -p k8s-mcp/src prometheus-mcp/src && echo "fn main() {}" > k8s-mcp/src/main.rs && echo "fn main() {}" > prometheus-mcp/src/main.rs
RUN cargo build --release -p loki-mcp 2>/dev/null || true
COPY . .
RUN cargo build --release -p loki-mcp

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/loki-mcp /usr/local/bin/
EXPOSE 3002
CMD ["loki-mcp"]
