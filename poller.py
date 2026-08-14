import os
import json
import time
from datetime import datetime, timezone

import requests
import processor
import monitor

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
PRODUCT_ID = os.environ["PRODUCT_ID"]
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"


def download_file(bucket, file_path):
    if file_path.startswith(bucket + "/"):
        file_path = file_path[len(bucket) + 1:]
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{file_path}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY})
    resp.raise_for_status()
    return resp.content


def get_headers():
    return {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def upload_result(job_id, content, filename):
    path = f"{job_id}/{filename}"
    url = f"{SUPABASE_URL}/storage/v1/object/results/{path}"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY, "Content-Type": "application/octet-stream"},
        data=content,
        timeout=60,
    )
    resp.raise_for_status()
    return f"results/{path}"


def update_job(job_id, payload):
    url = f"{SUPABASE_REST}/jobs?id=eq.{job_id}"
    resp = requests.patch(url, headers=get_headers(), json=payload, timeout=30)
    resp.raise_for_status()


def insert_notification(product_id, customer_id, title, body, ntype):
    try:
        url = f"{SUPABASE_REST}/notifications"
        payload = {
            "product_id": product_id,
            "customer_id": customer_id,
            "title": title,
            "body": body,
            "type": ntype,
            "read": False,
        }
        requests.post(url, headers=get_headers(), json=payload, timeout=30)
    except Exception:
        pass


def send_slack(text):
    """Post an alert to Slack when SLACK_WEBHOOK_URL is configured."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        return
    try:
        requests.post(webhook, json={"text": text}, timeout=10)
    except Exception:
        pass


def get_github_connection(customer_id):
    """Per-user GitHub connection (access token + username), if any."""
    if not customer_id:
        return None
    try:
        url = f"{SUPABASE_REST}/github_connections?user_id=eq.{customer_id}&select=github_username,access_token"
        resp = requests.get(url, headers=get_headers(), timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    except Exception:
        return None


def github_manifest(owner=None, token=None):
    """Build a source manifest from GitHub Actions runs.

    Uses the given owner/token (per-user connection) when provided,
    otherwise falls back to the deployment-level env vars.
    """
    owner = owner or os.environ.get("GITHUB_SOURCE_OWNER")
    token = token or os.environ.get("GITHUB_TOKEN")
    if not owner or not token:
        return None
    try:
        import github_connector
        rows = github_connector.discover_sources(owner, token=token)
        if not rows:
            return None
        return json.dumps({"sources": rows})
    except Exception as exc:
        raise RuntimeError("github_connector error: {}".format(exc)) from exc


def _insert_records(results, customer_id, input_path):
    rec_url = f"{SUPABASE_REST}/records"
    resp = requests.post(rec_url, headers=get_headers(), json=results, timeout=60)
    resp.raise_for_status()


def process_job(job):
    job_id = job.get("id")
    customer_id = job.get("customer_id")
    input_path = job.get("input_file_path", "")
    job_type = job.get("job_type") or "process_upload"
    try:
        file_bytes = b""
        if input_path:
            try:
                file_bytes = download_file("uploads", input_path)
            except Exception:
                file_bytes = b""
        if job_type == "process_sources":
            manifest_text = file_bytes.decode("utf-8-sig", "replace").strip() if file_bytes else ""
            if not manifest_text:
                conn = get_github_connection(customer_id)
                if conn:
                    manifest_text = github_manifest(owner=conn.get("github_username"), token=conn.get("access_token"))
                    if not manifest_text:
                        raise ValueError("No sources extracted — no GitHub Actions workflow runs found for the connected account")
                elif os.environ.get("GITHUB_TOKEN"):
                    manifest_text = github_manifest()
                else:
                    raise ValueError("No GitHub connection found — connect your GitHub account from the dashboard")
            if manifest_text:
                records = monitor.process_sources(manifest_text)
            else:
                records = []
            noun = "sources"
        else:
            records = processor.process_file(file_bytes)
            noun = "records"
        if not records:
            raise ValueError(f"No {noun} extracted")
        results = []
        for rec in records:
            row = {
                "product_id": PRODUCT_ID,
                "customer_id": customer_id,
                "title": rec.get("title") or "Untitled",
                "status": rec.get("status") or "valid:good",
                "details": rec,
                "source_file_path": input_path,
            }
            if rec.get("due_date"):
                row["due_date"] = rec["due_date"]
            results.append(row)
        _insert_records(results, customer_id, input_path)
        result_bytes = json.dumps(results, indent=2).encode("utf-8")
        output_path = upload_result(job_id, result_bytes, "result.json")
        now = datetime.now(timezone.utc).isoformat()
        update_job(job_id, {
            "status": "completed",
            "output_file_path": output_path,
            "result_summary": f"Processed {len(results)} {noun}",
            "completed_at": now,
        })
        insert_notification(PRODUCT_ID, customer_id, "Processing complete", "Your upload has been processed successfully.", "success")
        if job_type == "process_sources":
            critical = [r.get("title") for r in results if str(r.get("status", "")).endswith(":critical")]
            if critical:
                insert_notification(PRODUCT_ID, customer_id, "Sources need attention", "Critical: " + ", ".join(critical[:5]), "error")
                send_slack(":rotating_light: IngestWatch: " + ", ".join(critical[:5]))
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        try:
            update_job(job_id, {
                "status": "failed",
                "result_summary": str(exc)[:500],
                "completed_at": now,
            })
        except Exception:
            pass
        insert_notification(PRODUCT_ID, customer_id, "Processing failed", "There was an error processing your upload.", "error")


def poll():
    while True:
        try:
            jobs_url = f"{SUPABASE_REST}/jobs"
            params = {
                "select": "*",
                "status": "eq.pending",
                "product_id": f"eq.{PRODUCT_ID}",
                "order": "created_at.asc",
                "limit": "1",
            }
            resp = requests.get(jobs_url, headers=get_headers(), params=params, timeout=30)
            resp.raise_for_status()
            jobs = resp.json()
            for job in jobs:
                process_job(job)
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    print("Poller started")
    poll()
