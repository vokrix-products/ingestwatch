"""Read-only GitHub Actions connector.

Discovers scheduled ingestion workflows and their runs via the GitHub REST
API (read-only, no write access required) and returns a source manifest
consumable by monitor.process_sources. Every workflow defined in a repo
becomes a source, so scheduled jobs that have never run still surface as
missing:critical instead of being silently dropped.
"""
import json
import os

import requests

API = "https://api.github.com"


def _headers(token):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "token {}".format(token)
    return headers


def list_repos(owner, token, per_page=100):
    """List repos accessible to the token, as full 'owner/name' refs.

    /user/repos works for GitHub App user tokens (ghu_...), classic PATs,
    and org members alike, returning every repo the token can read. Falls
    back to public org/user listings when the token cannot use it.
    """
    url = "{}/user/repos".format(API)
    resp = requests.get(url, headers=_headers(token), params={"per_page": per_page, "sort": "updated", "visibility": "all"}, timeout=30)
    if resp.status_code == 200:
        return [
            r.get("full_name") or "{}/{}".format((r.get("owner") or {}).get("login"), r.get("name"))
            for r in resp.json()
            if r.get("name")
        ]
    if owner:
        for base in ("orgs", "users"):
            url = "{}/{}/{}/repos".format(API, base, owner)
            resp = requests.get(url, headers=_headers(token), params={"per_page": per_page, "sort": "updated"}, timeout=30)
            if resp.status_code == 200:
                return ["{}/{}".format(owner, r.get("name")) for r in resp.json() if r.get("name")]
    raise RuntimeError("GitHub API {} {}: {}".format(resp.status_code, url, resp.text[:300]))


def workflows(owner, repo, token):
    """All Actions workflows defined in a repo (.github/workflows/*.yml)."""
    url = "{}/repos/{}/{}/actions/workflows".format(API, owner, repo)
    try:
        resp = requests.get(url, headers=_headers(token), params={"per_page": 100}, timeout=30)
    except Exception:
        return []
    if resp.status_code != 200:
        raise RuntimeError("GitHub API {} {}: {}".format(resp.status_code, url, resp.text[:300]))
    return resp.json().get("workflows", []) or []


def workflow_latest_run(owner, repo, workflow_id, token):
    """Newest run for a workflow, or None if it has never run."""
    url = "{}/repos/{}/{}/actions/workflows/{}/runs".format(API, owner, repo, workflow_id)
    try:
        resp = requests.get(url, headers=_headers(token), params={"per_page": 1}, timeout=30)
    except Exception:
        return None
    if resp.status_code != 200:
        raise RuntimeError("GitHub API {} {}: {}".format(resp.status_code, url, resp.text[:300]))
    runs = resp.json().get("workflow_runs", []) or []
    return runs[0] if runs else None


def _map_workflow(workflow, run, owner, repo):
    name = workflow.get("name") or workflow.get("path") or "workflow"
    run_id = run_url = created = None
    conclusion = None
    if run:
        run_id = run.get("id")
        run_url = run.get("html_url")
        created = run.get("created_at") or run.get("updated_at")
        conclusion = run.get("conclusion")
    if not run:
        mapped = "missing"
    elif conclusion == "success":
        mapped = "success"
    elif conclusion in ("failure", "cancelled", "timed_out", "action_required", "startup_failure"):
        mapped = "failed"
    elif conclusion:
        mapped = conclusion
    else:
        mapped = run.get("status") or "unknown"
    is_failure = mapped == "failed"
    return {
        "source_name": "{}/{}".format(repo, name),
        "source_type": "github_actions",
        "source_url": workflow.get("html_url"),
        "repo_owner": owner,
        "repo_name": repo,
        "workflow_id": str(workflow.get("id")),
        "run_id": run_id,
        "run_url": run_url,
        "last_run_at": created,
        "status": mapped,
        "error_message": conclusion if is_failure else None,
        "alert_reason": "Workflow has never run" if not run else None,
        "empty_run": not run,
        "schedule": None,
        "workflow_path": workflow.get("path"),
    }


def discover_sources(owner, token=None, repos=None, days=7):
    """Return manifest rows (one per workflow source) for the given repos.

    Every workflow defined in a repo becomes a source, so scheduled jobs
    that have never run still surface as missing:critical instead of
    being silently dropped.
    """
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        return []
    repo_refs = repos or list_repos(owner, token)
    rows = []
    errors = []
    for ref in repo_refs:
        if "/" in ref:
            repo_owner, repo_name = ref.split("/", 1)
        else:
            repo_owner, repo_name = owner, ref
        try:
            for wf in workflows(repo_owner, repo_name, token):
                run = workflow_latest_run(repo_owner, repo_name, wf.get("id"), token)
                rows.append(_map_workflow(wf, run, repo_owner, repo_name))
        except Exception as exc:
            errors.append("{}: {}".format(ref, str(exc)[:200]))
    if not rows and errors:
        raise RuntimeError("; ".join(errors[:3]))
    if not rows and repo_refs:
        raise RuntimeError(
            "found {} repos but zero workflows - token may lack Actions read permission".format(len(repo_refs))
        )
    return rows


def build_manifest(owner, token=None, repos=None, days=7):
    """JSON source manifest ready for monitor.process_sources."""
    return json.dumps({"sources": discover_sources(owner, token=token, repos=repos, days=days)})
