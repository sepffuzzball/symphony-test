---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: my-project
polling:
  interval_ms: 30000
workspace:
  root: ./workspaces
agent:
  max_concurrent_agents: 4
  max_turns: 20
codex:
  command: codex app-server
  approval_policy: never
  thread_sandbox: workspace-write
---
You are working on ticket {{ issue.identifier }}: {{ issue.title }}.
{% if attempt %}This is retry attempt #{{ attempt }}.{% endif %}
