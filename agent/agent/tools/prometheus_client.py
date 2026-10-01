"""
Prometheus-MCP Client — HTTP client for the Prometheus MCP server.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.config import Config


class PrometheusMCPClient:
    """Client for the Prometheus-MCP server (port 3001)."""

    # Valid metric types — prevents the LLM from requesting arbitrary queries
    VALID_METRIC_TYPES = frozenset({
        "check_cpu_saturation",
        "check_5xx_rate",
        "check_db_connections",
        "check_memory_usage",
    })

    def __init__(self, config: Config):
        self.base_url = config.prometheus_mcp_url
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=15.0,
        )

    async def query_anomaly(
        self,
        metric_type: str,
        resource_name: str,
        namespace: str = "workload",
    ) -> dict[str, Any]:
        """
        Query for anomalies using pre-built PromQL templates.

        Args:
            metric_type: One of check_cpu_saturation, check_5xx_rate,
                         check_db_connections, check_memory_usage
            resource_name: Pod, deployment, or service name to filter on
            namespace: Target namespace
        """
        if metric_type not in self.VALID_METRIC_TYPES:
            return {
                "error": f"Invalid metric_type '{metric_type}'. Valid options: {', '.join(sorted(self.VALID_METRIC_TYPES))}",
                "metric_type": metric_type,
                "resource_name": resource_name,
            }

        resp = await self._client.post(
            "/query_anomaly",
            json={
                "metric_type": metric_type,
                "resource_name": resource_name,
                "namespace": namespace,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
