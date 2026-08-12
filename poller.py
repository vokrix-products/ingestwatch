import os
import json
import time
from datetime import datetime, timezone

import requests
import processor

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
PRODUCT_ID = os.environ["PRODUCT_ID"]
try:
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
except Exception:
    ANTHROPIC_API_KEY = ""
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


def poll():
    while True:
        try:
            jobs_url = f"{SUPABASE_REST}/jobs"
            params = {
                "select": "*",
                "status": "eq.pending",
                "job_type": "eq.process_upload",
                "product_id": f"eq.{PRODUCT_ID}",
                "order": "created_at.asc",
                "limit": "1",
            }
            resp = requests.get(jobs_url, headers=get_headers(), params=params, timeout=30)
            resp.raise_for_status()
            jobs = resp.json()
            for job in jobs:
                job_id = job.get("id")
                customer_id = job.get("customer_id")
                input_path = job.get("input_file_path", "")
                try:
                    file_bytes = download_file("uploads", input_path)
                    records = processor.process_file(file_bytes)
                    if not records:
                        raise ValueError("No records extracted")
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
                    rec_url = f"{SUPABASE_REST}/records"
                    resp2 = requests.post(rec_url, headers=get_headers(), json=results, timeout=60)
                    resp2.raise_for_status()
                    result_bytes = json.dumps(results, indent=2).encode("utf-8")
                    output_path = upload_result(job_id, result_bytes, "result.json")
                    now = datetime.now(timezone.utc).isoformat()
                    update_job(job_id, {
                        "status": "completed",
                        "output_file_path": output_path,
                        "result_summary": f"Processed {len(results)} records",
                        "completed_at": now,
                    })
                    insert_notification(PRODUCT_ID, customer_id, "Processing complete", "Your upload has been processed successfully.", "success")
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
        except Exception:
            pass
        time.sleep(60)


if __name__ == "__main__":
    print("Poller started")
    poll()
