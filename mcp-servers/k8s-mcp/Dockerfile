FROM rust:slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml ./
COPY k8s-mcp/ k8s-mcp/
COPY prometheus-mcp/Cargo.toml prometheus-mcp/Cargo.toml
COPY loki-mcp/Cargo.toml loki-mcp/Cargo.toml
RUN mkdir -p prometheus-mcp/src loki-mcp/src && echo "fn main() {}" > prometheus-mcp/src/main.rs && echo "fn main() {}" > loki-mcp/src/main.rs
RUN cargo build --release -p k8s-mcp 2>/dev/null || true
COPY . .
RUN cargo build --release -p k8s-mcp

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/k8s-mcp /usr/local/bin/
EXPOSE 3000
CMD ["k8s-mcp"]
