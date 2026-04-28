from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .linear import LinearClient
from .models import Issue, ServiceConfig, WorkflowDefinition
from .runtime import ensure_workspace, run_agent, run_hook
from .workflow import WorkflowError, load_workflow, render_prompt, resolve_config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetryEntry:
    attempt: int
    due_at: float
    error: str | None = None


@dataclass(slots=True)
class RuntimeState:
    running: set[str] = field(default_factory=set)
    claimed: set[str] = field(default_factory=set)
    retries: dict[str, RetryEntry] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, workflow_path: str | Path | None = None):
        self.workflow_path = Path(workflow_path) if workflow_path else Path.cwd() / "WORKFLOW.md"
        self.workflow_mtime: float | None = None
        self.workflow: WorkflowDefinition | None = None
        self.config: ServiceConfig | None = None
        self.state = RuntimeState()

    def _reload_if_needed(self) -> None:
        try:
            mtime = self.workflow_path.stat().st_mtime
        except FileNotFoundError as exc:
            raise WorkflowError("missing_workflow_file", str(exc)) from exc

        if self.workflow is None or self.workflow_mtime is None or mtime > self.workflow_mtime:
            workflow = load_workflow(self.workflow_path)
            config = resolve_config(workflow, self.workflow_path)
            self.workflow = workflow
            self.config = config
            self.workflow_mtime = mtime
            logger.info("workflow_reloaded path=%s", self.workflow_path)

    async def _run_issue(self, issue: Issue, attempt: int | None = None) -> None:
        assert self.workflow and self.config
        issue_id = issue.id
        try:
            workspace, _ = await ensure_workspace(self.config, issue.identifier)
            if script := self.config.hooks.get("before_run"):
                code, out, err = await run_hook(script, workspace, self.config.hooks_timeout_ms)
                if code != 0:
                    raise RuntimeError(f"before_run failed ({code}): {err or out}")

            prompt = render_prompt(self.workflow.prompt_template, issue, attempt)
            rc = await run_agent(self.config, prompt, workspace)

            if script := self.config.hooks.get("after_run"):
                code, out, err = await run_hook(script, workspace, self.config.hooks_timeout_ms)
                if code != 0:
                    logger.warning("after_run_failed issue=%s code=%s err=%s", issue.identifier, code, err or out)

            if rc != 0:
                raise RuntimeError(f"agent exited with {rc}")
            self.state.retries.pop(issue_id, None)
        except Exception as exc:  # retry path
            logger.exception("run_failed issue=%s: %s", issue.identifier, exc)
            prev = self.state.retries.get(issue_id)
            n = 1 if prev is None else prev.attempt + 1
            backoff_ms = min(self.config.max_retry_backoff_ms, 2 ** min(n, 10) * 1000)
            self.state.retries[issue_id] = RetryEntry(attempt=n, due_at=time.monotonic() + (backoff_ms / 1000), error=str(exc))
        finally:
            self.state.running.discard(issue_id)

    async def run_forever(self) -> None:
        while True:
            self._reload_if_needed()
            assert self.config
            await self._tick()
            await asyncio.sleep(self.config.poll_interval_ms / 1000)

    async def _tick(self) -> None:
        assert self.config
        if self.config.tracker_kind != "linear" or not self.config.tracker_api_key or not self.config.tracker_project_slug:
            logger.error("invalid tracker config; dispatch blocked")
            return

        client = LinearClient(
            endpoint=self.config.tracker_endpoint,
            api_key=self.config.tracker_api_key,
            project_slug=self.config.tracker_project_slug,
        )
        issues = await client.fetch_candidate_issues(self.config.active_states)

        # Reconciliation: stop claimed issues now in terminal states.
        term = {s.lower() for s in self.config.terminal_states}
        for issue_id in list(self.state.claimed):
            state = await client.fetch_issue_state(issue_id)
            if state and state.lower() in term:
                self.state.claimed.discard(issue_id)
                self.state.running.discard(issue_id)
                self.state.retries.pop(issue_id, None)

        now = time.monotonic()
        issue_by_id = {i.id: i for i in issues}

        # Queue due retries first.
        dispatch: list[tuple[Issue, int | None]] = []
        for issue_id, retry in list(self.state.retries.items()):
            if retry.due_at <= now and issue_id in issue_by_id:
                dispatch.append((issue_by_id[issue_id], retry.attempt))

        for issue in issues:
            if issue.id in self.state.claimed:
                continue
            dispatch.append((issue, None))

        available = max(0, self.config.max_concurrent_agents - len(self.state.running))
        for issue, attempt in dispatch[:available]:
            by_state_cap = self.config.max_concurrent_agents_by_state.get(issue.state.lower())
            if by_state_cap is not None:
                running_in_state = 0
                for running_id in self.state.running:
                    ri = issue_by_id.get(running_id)
                    if ri and ri.state.lower() == issue.state.lower():
                        running_in_state += 1
                if running_in_state >= by_state_cap:
                    continue
            self.state.claimed.add(issue.id)
            self.state.running.add(issue.id)
            asyncio.create_task(self._run_issue(issue, attempt))
