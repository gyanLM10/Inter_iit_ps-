"""
Agent configuration — MCP server URLs, LLM provider, thresholds.
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """RCA Agent configuration."""

    # MCP Server URLs
    k8s_mcp_url: str = field(
        default_factory=lambda: os.getenv("K8S_MCP_URL", "http://localhost:3000")
    )
    prometheus_mcp_url: str = field(
        default_factory=lambda: os.getenv("PROMETHEUS_MCP_URL", "http://localhost:3001")
    )
    loki_mcp_url: str = field(
        default_factory=lambda: os.getenv("LOKI_MCP_URL", "http://localhost:3002")
    )

    # LLM Configuration
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "google")  # "google" or "openai"
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gemini-2.0-flash")
    )
    google_api_key: str = field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY", "")
    )
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )

    # Agent Behavior
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("MAX_ITERATIONS", "5"))
    )
    confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.9"))
    )

    # Target namespace to investigate
    target_namespace: str = field(
        default_factory=lambda: os.getenv("TARGET_NAMESPACE", "workload")
    )


def get_config() -> Config:
    """Get the agent configuration."""
    return Config()
