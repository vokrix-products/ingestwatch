"""Read-only GitHub Actions connector.

Discovers scheduled ingestion workflows and their recent runs via the
GitHub REST API (read-only, no write access required) and returns a source
manifest consumable by monitor.process_sources.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.github.com"


def _headers(token):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "token {}".format(token)
    return headers


def list_repos(owner, token, per_page=100):
    """List repo names for an org (falling back to a user account)."""
    url = "{}/orgs/{}/repos".format(API, owner)
    resp = requests.get(url, headers=_headers(token), params={"per_page": per_page, "sort": "updated"}, timeout=30)
    if resp.status_code != 200:
        url = "{}/users/{}/repos".format(API, owner)
        resp = requests.get(url, headers=_headers(token), params={"per_page": per_page, "sort": "updated"}, timeout=30)
    if resp.status_code != 200:
        return []
    return [r.get("name") for r in resp.json() if r.get("name")]


def workflow_runs(owner, repo, token, days=7):
    """Recent workflow runs for one repo, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = "{}/repos/{}/{}/actions/runs".format(API, owner, repo)
    try:
        resp = requests.get(url, headers=_headers(token), params={"per_page": 100}, timeout=30)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    out = []
    for run in resp.json().get("workflow_runs", []) or []:
        created = run.get("created_at")
        if created and created < since:
            continue
        out.append(run)
    return out


def _map_run(run, owner, repo):
    workflow_id = run.get("workflow_id") or run.get("name") or "workflow"
    conclusion = run.get("conclusion")
    status_raw = run.get("status")
    if conclusion == "success":
        mapped = "success"
    elif conclusion == "failure":
        mapped = "failed"
    elif conclusion in ("cancelled", "timed_out", "action_required", "startup_failure"):
        mapped = "failed"
    elif conclusion:
        mapped = conclusion
    else:
        mapped = status_raw or "unknown"
    is_failure = mapped == "failed"
    return {
        "source_name": "{}/{}".format(repo, workflow_id),
        "source_type": "github_actions",
        "source_url": run.get("html_url"),
        "repo_owner": owner,
        "repo_name": repo,
        "workflow_id": str(workflow_id),
        "run_id": run.get("id"),
        "run_url": run.get("html_url"),
        "last_run_at": run.get("created_at") or run.get("updated_at"),
        "status": mapped,
        "error_message": conclusion if is_failure else None,
    }


def discover_sources(owner, token=None, repos=None, days=7):
    """Return manifest rows (one per source, latest run) for the given repos."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        return []
    repo_names = repos or list_repos(owner, token)
    rows = []
    for repo in repo_names:
        for run in workflow_runs(owner, repo, token, days):
            rows.append(_map_run(run, owner, repo))
    unique = []
    seen = set()
    for row in rows:
        key = row["source_name"]
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def build_manifest(owner, token=None, repos=None, days=7):
    """JSON source manifest ready for monitor.process_sources."""
    return json.dumps({"sources": discover_sources(owner, token=token, repos=repos, days=days)})
