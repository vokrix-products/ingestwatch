import csv
import io
import json
from datetime import datetime, timedelta, timezone

from processor import process_file
from monitor import process_sources


def ts(hours_from_now):
    """UTC timestamp relative to now, e.g. ts(-24) = 24h ago."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
                "last_run_at": ts(-24),
                "next_run_at": ts(24),
                "status": "success",
                "fetched_count": 120,
                "scored_count": 118,
                "qualified_count": 115,
            },
            {
                "source_name": "salesforce-sync",
                "workflow_id": "sync.yml",
                "schedule": "0 */6 * * *",
                "last_run_at": ts(-24),
                "next_run_at": ts(-18),
                "status": "success",
                "fetched_count": 0,
            },
            {
                "source_name": "hubspot-contacts",
                "workflow_id": "contacts.yml",
                "schedule": "0 4 * * 1",
                "last_run_at": None,
                "next_run_at": ts(-1),
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
