from __future__ import annotations

import json
from typing import Any
from urllib import request

from .models import Issue


class LinearClient:
    def __init__(self, endpoint: str, api_key: str, project_slug: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.project_slug = project_slug

    async def _query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errors"):
            raise RuntimeError(f"Linear GraphQL error: {data['errors']}")
        return data["data"]

    async def fetch_candidate_issues(self, active_states: list[str]) -> list[Issue]:
        query = """
        query CandidateIssues($slug: String!, $states: [String!]) {
          projects(filter: {slug: {eq: $slug}}) {
            nodes {
              issues(filter: {state: {name: {in: $states}}}, first: 50) {
                nodes { id identifier title description priority url branchName state { name } labels { nodes { name } } }
              }
            }
          }
        }
        """
        data = await self._query(query, {"slug": self.project_slug, "states": active_states})
        projects = data.get("projects", {}).get("nodes", [])
        out: list[Issue] = []
        for project in projects:
            for node in project.get("issues", {}).get("nodes", []):
                out.append(self._normalize_issue(node))
        return out

    async def fetch_issue_state(self, issue_id: str) -> str | None:
        query = "query IssueState($id: String!) { issue(id: $id) { state { name } } }"
        data = await self._query(query, {"id": issue_id})
        issue = data.get("issue")
        if not issue:
            return None
        state = issue.get("state") or {}
        return state.get("name")

    def _normalize_issue(self, raw: dict[str, Any]) -> Issue:
        labels = [str(n.get("name", "")).lower() for n in (raw.get("labels") or {}).get("nodes", []) if n.get("name")]
        return Issue(
            id=raw["id"],
            identifier=raw["identifier"],
            title=raw.get("title") or "",
            description=raw.get("description"),
            priority=raw.get("priority"),
            state=((raw.get("state") or {}).get("name") or ""),
            branch_name=raw.get("branchName"),
            url=raw.get("url"),
            labels=labels,
            blocked_by=[],
        )
