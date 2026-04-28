from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .models import Issue, ServiceConfig, WorkflowDefinition


class WorkflowError(Exception):
    code: str

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _parse_scalar(text: str) -> Any:
    t = text.strip()
    if t in {"", "null", "Null", "NULL", "~"}:
        return None
    if t.lower() == "true":
        return True
    if t.lower() == "false":
        return False
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        return t[1:-1]
    try:
        return int(t)
    except ValueError:
        return t


def _parse_simple_yaml(text: str) -> Any:
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    def parse_block(i: int, indent: int) -> tuple[Any, int]:
        if i >= len(lines):
            return {}, i
        is_list = lines[i].lstrip().startswith("- ") and (len(lines[i]) - len(lines[i].lstrip(" "))) == indent
        if is_list:
            arr: list[Any] = []
            while i < len(lines):
                raw = lines[i]
                cur_indent = len(raw) - len(raw.lstrip(" "))
                if cur_indent < indent or not raw.lstrip().startswith("- "):
                    break
                if cur_indent > indent:
                    raise WorkflowError("workflow_parse_error", f"Unexpected indent at line: {raw.strip()}")
                item_text = raw.lstrip()[2:].strip()
                i += 1
                if item_text:
                    arr.append(_parse_scalar(item_text))
                else:
                    child, i = parse_block(i, indent + 2)
                    arr.append(child)
            return arr, i

        obj: dict[str, Any] = {}
        while i < len(lines):
            raw = lines[i]
            cur_indent = len(raw) - len(raw.lstrip(" "))
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise WorkflowError("workflow_parse_error", f"Unexpected indent at line: {raw.strip()}")
            line = raw.strip()
            if line.startswith("- "):
                break
            if ":" not in line:
                raise WorkflowError("workflow_parse_error", f"Invalid line: {line}")
            key, rest = line.split(":", 1)
            key, rest = key.strip(), rest.strip()
            i += 1
            if rest:
                obj[key] = _parse_scalar(rest)
            else:
                child, i = parse_block(i, indent + 2)
                obj[key] = child
        return obj, i

    parsed, idx = parse_block(0, 0)
    if idx != len(lines):
        raise WorkflowError("workflow_parse_error", "Could not parse full YAML front matter")
    return parsed


def _fix_list_nodes(node: Any) -> Any:
    if isinstance(node, dict):
        for k, v in list(node.items()):
            node[k] = _fix_list_nodes(v)
            if isinstance(node[k], dict) and not node[k]:
                node[k] = {}
    elif isinstance(node, list):
        for i, v in enumerate(node):
            node[i] = _fix_list_nodes(v)
    return node


def load_workflow(path: str | Path | None = None) -> WorkflowDefinition:
    workflow_path = Path(path or Path.cwd() / "WORKFLOW.md")
    if not workflow_path.exists():
        raise WorkflowError("missing_workflow_file", f"Workflow file not found: {workflow_path}")

    raw = workflow_path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        match = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, flags=re.DOTALL)
        if not match:
            raise WorkflowError("workflow_parse_error", "Invalid YAML front matter delimiter usage")
        fm_text, body = match.groups()
        parsed = _parse_simple_yaml(fm_text) if fm_text.strip() else {}
        parsed = _fix_list_nodes(parsed)
        if not isinstance(parsed, dict):
            raise WorkflowError("workflow_front_matter_not_a_map", "Front matter must decode to an object")
        return WorkflowDefinition(config=parsed, prompt_template=body.strip())

    return WorkflowDefinition(config={}, prompt_template=raw.strip())


def _resolve_env_token(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("$") and len(value) > 1:
        resolved = os.getenv(value[1:], "")
        return resolved or None
    return value


def _as_int(value: Any, default: int, *, min_value: int | None = None, field_name: str = "value") -> int:
    if value is None:
        out = default
    elif isinstance(value, bool):
        raise WorkflowError("workflow_parse_error", f"{field_name} must be an integer")
    else:
        try:
            out = int(value)
        except (TypeError, ValueError) as exc:
            raise WorkflowError("workflow_parse_error", f"{field_name} must be an integer") from exc
    if min_value is not None and out < min_value:
        raise WorkflowError("workflow_parse_error", f"{field_name} must be >= {min_value}")
    return out


def resolve_config(defn: WorkflowDefinition, workflow_path: str | Path | None = None) -> ServiceConfig:
    workflow_path = Path(workflow_path or Path.cwd() / "WORKFLOW.md").resolve()
    workflow_dir = workflow_path.parent
    c = defn.config

    tracker = c.get("tracker") or {}
    polling = c.get("polling") or {}
    workspace = c.get("workspace") or {}
    hooks_cfg = c.get("hooks") or {}
    agent = c.get("agent") or {}
    codex = c.get("codex") or {}

    workspace_root = workspace.get("root")
    if isinstance(workspace_root, str):
        workspace_root = _resolve_env_token(workspace_root) or workspace_root
        workspace_root = os.path.expanduser(workspace_root)
        root_path = Path(workspace_root)
        if not root_path.is_absolute():
            root_path = (workflow_dir / root_path).resolve()
    else:
        root_path = Path("/tmp/symphony_workspaces").resolve()

    raw_state_caps = agent.get("max_concurrent_agents_by_state") or {}
    state_caps: dict[str, int] = {}
    if isinstance(raw_state_caps, dict):
        for k, v in raw_state_caps.items():
            try:
                iv = int(v)
            except (TypeError, ValueError):
                continue
            if iv > 0:
                state_caps[str(k).lower()] = iv

    hooks: dict[str, str] = {}
    for key in ("after_create", "before_run", "after_run", "before_remove"):
        val = hooks_cfg.get(key)
        if isinstance(val, str) and val.strip():
            hooks[key] = val

    return ServiceConfig(
        workflow_path=workflow_path,
        workflow_dir=workflow_dir,
        tracker_kind=tracker.get("kind"),
        tracker_endpoint=tracker.get("endpoint") or "https://api.linear.app/graphql",
        tracker_api_key=_resolve_env_token(tracker.get("api_key") or "$LINEAR_API_KEY"),
        tracker_project_slug=tracker.get("project_slug"),
        active_states=tracker.get("active_states") or ["Todo", "In Progress"],
        terminal_states=tracker.get("terminal_states") or ["Closed", "Cancelled", "Canceled", "Duplicate", "Done"],
        poll_interval_ms=_as_int(polling.get("interval_ms"), 30000, min_value=1, field_name="polling.interval_ms"),
        workspace_root=root_path,
        hooks=hooks,
        hooks_timeout_ms=_as_int(hooks_cfg.get("timeout_ms"), 60000, min_value=1, field_name="hooks.timeout_ms"),
        max_concurrent_agents=_as_int(agent.get("max_concurrent_agents"), 10, min_value=1, field_name="agent.max_concurrent_agents"),
        max_turns=_as_int(agent.get("max_turns"), 20, min_value=1, field_name="agent.max_turns"),
        max_retry_backoff_ms=_as_int(agent.get("max_retry_backoff_ms"), 300000, min_value=1, field_name="agent.max_retry_backoff_ms"),
        max_concurrent_agents_by_state=state_caps,
        codex_command=codex.get("command") or "codex app-server",
        codex_approval_policy=codex.get("approval_policy"),
        codex_thread_sandbox=codex.get("thread_sandbox"),
        codex_turn_sandbox_policy=codex.get("turn_sandbox_policy"),
        codex_turn_timeout_ms=_as_int(codex.get("turn_timeout_ms"), 3600000, min_value=1, field_name="codex.turn_timeout_ms"),
        codex_read_timeout_ms=_as_int(codex.get("read_timeout_ms"), 5000, min_value=1, field_name="codex.read_timeout_ms"),
        codex_stall_timeout_ms=_as_int(codex.get("stall_timeout_ms"), 300000, field_name="codex.stall_timeout_ms"),
    )


def _resolve_expr(expr: str, issue: Issue, attempt: int | None) -> str:
    expr = expr.strip()
    if "|" in expr:
        raise WorkflowError("template_render_error", f"Unknown filter in expression: {expr}")
    if expr == "attempt":
        return "" if attempt is None else str(attempt)
    if expr.startswith("issue."):
        field = expr[6:]
        if not hasattr(issue, field):
            raise WorkflowError("template_render_error", f"Unknown variable: {expr}")
        value = getattr(issue, field)
        return "" if value is None else str(value)
    raise WorkflowError("template_render_error", f"Unknown variable: {expr}")


def render_prompt(prompt_template: str, issue: Issue, attempt: int | None) -> str:
    text = prompt_template or "You are working on an issue from Linear."

    # minimal liquid-compatible branch for {% if attempt %}...{% endif %}
    text = re.sub(
        r"\{%-?\s*if\s+attempt\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}",
        lambda m: m.group(1) if attempt else "",
        text,
        flags=re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        return _resolve_expr(match.group(1), issue, attempt)

    try:
        return re.sub(r"\{\{\s*(.*?)\s*\}\}", repl, text)
    except re.error as exc:
        raise WorkflowError("template_parse_error", str(exc)) from exc
