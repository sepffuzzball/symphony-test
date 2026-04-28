from pathlib import Path

import pytest

from symphony.models import Issue
from symphony.runtime import workspace_key
from symphony.workflow import WorkflowError, load_workflow, render_prompt, resolve_config


def test_load_workflow_with_front_matter(tmp_path: Path):
    wf = tmp_path / "WORKFLOW.md"
    wf.write_text("---\ntracker:\n  kind: linear\n---\nHello {{ issue.identifier }}\n")
    d = load_workflow(wf)
    assert d.config["tracker"]["kind"] == "linear"
    assert d.prompt_template == "Hello {{ issue.identifier }}"


def test_front_matter_non_map_fails(tmp_path: Path):
    wf = tmp_path / "WORKFLOW.md"
    wf.write_text("---\n- nope\n---\ntext")
    with pytest.raises(WorkflowError) as exc:
        load_workflow(wf)
    assert exc.value.code == "workflow_front_matter_not_a_map"


def test_resolve_workspace_relative_to_workflow(tmp_path: Path):
    wf = tmp_path / "WORKFLOW.md"
    wf.write_text("---\nworkspace:\n  root: ./abc\n---\nbody")
    d = load_workflow(wf)
    c = resolve_config(d, wf)
    assert c.workspace_root == (tmp_path / "abc").resolve()


def test_strict_prompt_errors_on_unknown_var():
    issue = Issue(
        id="1",
        identifier="ABC-1",
        title="x",
        description=None,
        priority=None,
        state="Todo",
        branch_name=None,
        url=None,
    )
    with pytest.raises(WorkflowError) as exc:
        render_prompt("{{ issue.nope }}", issue, None)
    assert exc.value.code == "template_render_error"


def test_workspace_key_sanitization():
    assert workspace_key("ABC/1 : test") == "ABC_1___test"
