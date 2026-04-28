from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Issue:
    id: str
    identifier: str
    title: str
    description: str | None
    priority: int | None
    state: str
    branch_name: str | None
    url: str | None
    labels: list[str] = field(default_factory=list)
    blocked_by: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowDefinition:
    config: dict[str, Any]
    prompt_template: str


@dataclass(slots=True)
class ServiceConfig:
    workflow_path: Path
    workflow_dir: Path
    tracker_kind: str | None
    tracker_endpoint: str
    tracker_api_key: str | None
    tracker_project_slug: str | None
    active_states: list[str]
    terminal_states: list[str]
    poll_interval_ms: int
    workspace_root: Path
    hooks: dict[str, str]
    hooks_timeout_ms: int
    max_concurrent_agents: int
    max_turns: int
    max_retry_backoff_ms: int
    max_concurrent_agents_by_state: dict[str, int]
    codex_command: str
    codex_approval_policy: str | None
    codex_thread_sandbox: str | None
    codex_turn_sandbox_policy: str | None
    codex_turn_timeout_ms: int
    codex_read_timeout_ms: int
    codex_stall_timeout_ms: int
