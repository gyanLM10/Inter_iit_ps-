"""
K8s-MCP Client — HTTP client for the Kubernetes MCP server.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.config import Config


class K8sMCPClient:
    """Client for the K8s-MCP server (port 3000)."""

    def __init__(self, config: Config):
        self.base_url = config.k8s_mcp_url
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=15.0,
        )

    async def list_recent_events(self, namespace: str) -> dict[str, Any]:
        """List recent warning/error events in a namespace."""
        resp = await self._client.post(
            "/list_recent_events",
            json={"namespace": namespace},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_pod_status(self, pod_name: str, namespace: str = "workload") -> dict[str, Any]:
        """Get detailed pod status including container states and exit codes."""
        import re
        clean_name = re.sub(r'^(?i)(pod|service|deployment|replicaset|statefulset)/', '', pod_name)
        resp = await self._client.post(
            "/get_pod_status",
            json={"pod_name": clean_name, "namespace": namespace},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_deployment_diff(
        self, deployment_name: str, namespace: str = "workload"
    ) -> dict[str, Any]:
        """Compare current vs previous ReplicaSet specs for a deployment."""
        import re
        clean_name = re.sub(r'^(?i)(pod|service|deployment|replicaset|statefulset)/', '', deployment_name)
        resp = await self._client.post(
            "/get_deployment_diff",
            json={"deployment_name": clean_name, "namespace": namespace},
        )
        resp.raise_for_status()
        return resp.json()

    async def check_network_policies(
        self, namespace: str = "workload"
    ) -> dict[str, Any]:
        """Check network policies in a namespace."""
        resp = await self._client.post(
            "/check_network_policies",
            json={"namespace": namespace},
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
