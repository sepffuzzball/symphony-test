# Symphony (Python)

A Python implementation of the OpenAI Symphony service specification.

## What is included

- `WORKFLOW.md` loader with YAML front matter + prompt body split.
- Typed config resolution with defaults, env-token indirection (`$VAR`), and workspace path normalization.
- Strict prompt rendering (unknown variables fail).
- Linear issue client (GraphQL) with issue normalization.
- Polling orchestrator with bounded concurrency, per-state caps, retry backoff, and reconciliation.
- Workspace manager and lifecycle hooks.
- Dynamic `WORKFLOW.md` reload by file mtime.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
symphony --workflow WORKFLOW.md
```

## Notes

- This implementation preserves in-memory scheduler state only while running.
- Retry scheduling uses exponential backoff capped by `agent.max_retry_backoff_ms`.
