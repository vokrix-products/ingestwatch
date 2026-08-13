import csv
import io
import json
from processor import process_file
from monitor import process_sources


def file_demo():
    rows = [
        {"source_name": "stripe", "status": "running", "due_date": "2026-01-15"},
        {"source_name": "salesforce", "status": "failed", "due_date": "2026-01-16", "error_message": "timeout"},
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["source_name", "status", "due_date", "error_message"])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    records = process_file(buf.getvalue().encode("utf-8"))
    assert isinstance(records, list)
    assert len(records) == len(rows)
    print(json.dumps(records, indent=2))


def monitor_demo():
    manifest = {
        "sources": [
            {
                "source_name": "stripe-import",
                "repo_owner": "acme",
                "workflow_id": "ingest.yml",
                "schedule": "0 3 * * *",
                "last_run_at": "2026-01-15T03:00:00Z",
                "next_run_at": "2026-01-16T03:00:00Z",
                "status": "success",
                "fetched_count": 120,
                "scored_count": 118,
                "qualified_count": 115,
            },
            {
                "source_name": "salesforce-sync",
                "workflow_id": "sync.yml",
                "schedule": "0 */6 * * *",
                "last_run_at": "2026-01-10T06:00:00Z",
                "next_run_at": "2026-01-10T12:00:00Z",
                "status": "success",
                "fetched_count": 0,
            },
            {
                "source_name": "hubspot-contacts",
                "workflow_id": "contacts.yml",
                "schedule": "0 4 * * 1",
                "last_run_at": None,
                "next_run_at": "2026-01-12T04:00:00Z",
            },
        ]
    }
    records = process_sources(json.dumps(manifest))
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    print("=== FILE NORMALIZATION ===")
    file_demo()
    print("=== SOURCE MONITORING ===")
    monitor_demo()
