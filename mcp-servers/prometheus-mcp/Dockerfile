FROM rust:slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml ./
COPY prometheus-mcp/ prometheus-mcp/
COPY k8s-mcp/Cargo.toml k8s-mcp/Cargo.toml
COPY loki-mcp/Cargo.toml loki-mcp/Cargo.toml
RUN mkdir -p k8s-mcp/src loki-mcp/src && echo "fn main() {}" > k8s-mcp/src/main.rs && echo "fn main() {}" > loki-mcp/src/main.rs
RUN cargo build --release -p prometheus-mcp 2>/dev/null || true
COPY . .
RUN cargo build --release -p prometheus-mcp

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/prometheus-mcp /usr/local/bin/
EXPOSE 3001
CMD ["prometheus-mcp"]
