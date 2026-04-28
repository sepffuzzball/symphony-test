from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from .models import ServiceConfig

logger = logging.getLogger(__name__)


def workspace_key(issue_identifier: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", issue_identifier)


async def run_hook(script: str, cwd: Path, timeout_ms: int) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "bash",
        "-lc",
        script,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_ms / 1000)
        return proc.returncode or 0, out.decode(), err.decode()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "", "hook timeout"


async def ensure_workspace(config: ServiceConfig, issue_identifier: str) -> tuple[Path, bool]:
    key = workspace_key(issue_identifier)
    path = config.workspace_root / key
    created_now = False
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        created_now = True
        if script := config.hooks.get("after_create"):
            code, out, err = await run_hook(script, path, config.hooks_timeout_ms)
            if code != 0:
                raise RuntimeError(f"after_create failed ({code}): {err or out}")
    return path, created_now


async def run_agent(config: ServiceConfig, prompt: str, workspace: Path) -> int:
    cmd = f"{config.codex_command} --prompt {prompt!r}"
    proc = await asyncio.create_subprocess_exec("bash", "-lc", cmd, cwd=str(workspace))
    try:
        await asyncio.wait_for(proc.wait(), timeout=config.codex_turn_timeout_ms / 1000)
        return proc.returncode or 0
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124
