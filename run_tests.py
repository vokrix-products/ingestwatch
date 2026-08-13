import csv
import io
import json
import unittest
from datetime import datetime, timedelta, timezone

from processor import STATUS_VALUES, process_file
from monitor import process_sources


def ts(hours_from_now):
    """UTC timestamp relative to now, e.g. ts(-24) = 24h ago."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProcessorTests(unittest.TestCase):
    def test_csv_fallback(self):
        data = "source_name,status,due_date\nfoo,running,2026-01-15\n"
        records = process_file(data.encode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "foo")
        self.assertIn(records[0]["status"], STATUS_VALUES)

    def test_plain_text_fallback(self):
        data = "Supplier: Acme Corp\nStatus: failed\nDue Date: 2026-01-20\n"
        records = process_file(data.encode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 1)

    def test_csv_company_header(self):
        data = "Company,Status,Due Date\nAcme Corp,active,2026-01-15\nGlobex,expired,2026-02-01\n"
        records = process_file(data.encode("utf-8"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Acme Corp")
        self.assertEqual(records[1]["title"], "Globex")
        self.assertEqual(records[0]["status"], "valid:good")
        self.assertEqual(records[1]["status"], "expired:warning")

    def test_csv_unknown_headers_first_column_fallback(self):
        data = "Name of Business,Current Status\nAcme Corp,running\n"
        records = process_file(data.encode("utf-8"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Acme Corp")
        self.assertIn(records[0]["status"], STATUS_VALUES)

    def test_plain_text_blocks_with_names(self):
        data = (
            "Acme Corp\nStatus: failed\nDue Date: 2026-01-20\n\n"
            "Globex\nStatus: valid\nDue Date: 2026-02-01\n"
        )
        records = process_file(data.encode("utf-8"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Acme Corp")
        self.assertEqual(records[1]["title"], "Globex")
        self.assertEqual(records[0]["status"], "failed:critical")
        self.assertEqual(records[1]["status"], "valid:good")
        self.assertEqual(records[0].get("due_date"), "2026-01-20")

    def test_plain_text_key_value_with_spaced_keys(self):
        data = "Supplier: Acme Corp\nStatus: failed\nDue Date: 2026-01-20\n"
        records = process_file(data.encode("utf-8"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Acme Corp")
        self.assertEqual(records[0]["status"], "failed:critical")
        self.assertEqual(records[0].get("due_date"), "2026-01-20")

    def test_plain_text_single_name_list(self):
        data = "Acme Corp\nGlobex\nInitech\n"
        records = process_file(data.encode("utf-8"))
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["title"], "Acme Corp")
        self.assertEqual(records[2]["title"], "Initech")


class MonitorTests(unittest.TestCase):
    def test_manifest_healthy_source(self):
        manifest = {
            "sources": [
                {
                    "source_name": "stripe-import",
                    "workflow_id": "ingest.yml",
                    "schedule": "0 3 * * *",
                    "last_run_at": ts(-24),
                    "next_run_at": ts(24),
                    "status": "success",
                    "fetched_count": 120,
                    "scored_count": 118,
                    "qualified_count": 115,
                }
            ]
        }
        records = process_sources(json.dumps(manifest))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["title"], "stripe-import")
        self.assertEqual(rec["status"], "valid:good")
        self.assertEqual(rec["fetched_count"], 120)
        self.assertEqual(rec.get("due_date"), (datetime.now(timezone.utc) + timedelta(hours=24)).date().isoformat())

    def test_manifest_failed_source(self):
        manifest = {"sources": [{"source_name": "sync", "status": "failed", "error_message": "timeout"}]}
        records = process_sources(json.dumps(manifest))
        self.assertEqual(records[0]["status"], "failed:critical")

    def test_manifest_empty_run(self):
        manifest = {"sources": [{"source_name": "feed", "status": "success", "fetched_count": 0}]}
        records = process_sources(json.dumps(manifest))
        self.assertEqual(records[0]["status"], "empty:warning")

    def test_manifest_missing_source(self):
        manifest = {"sources": [{"source_name": "ghost", "last_run_at": None, "next_run_at": None}]}
        records = process_sources(json.dumps(manifest))
        self.assertEqual(records[0]["status"], "missing:critical")

    def test_manifest_stale_source(self):
        manifest = {"sources": [{"source_name": "old", "schedule": "0 3 * * *", "last_run_at": ts(-24 * 30), "next_run_at": ts(-24 * 30 + 24)}]}
        records = process_sources(json.dumps(manifest))
        self.assertEqual(records[0]["status"], "expired:warning")

    def test_manifest_csv(self):
        data = (
            "source_name,status,fetched_count,scored_count,qualified_count,last_run_at,next_run_at\n"
            f"stripe-import,success,120,118,115,{ts(-24)},{ts(24)}\n"
        )
        records = process_sources(data)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "stripe-import")
        self.assertEqual(records[0]["status"], "valid:good")

    def test_manifest_bytes(self):
        manifest = {"sources": [{"source_name": "bytes-src", "status": "success", "fetched_count": 5}]}
        records = process_sources(json.dumps(manifest).encode("utf-8"))
        self.assertEqual(records[0]["title"], "bytes-src")
        self.assertEqual(records[0]["status"], "valid:good")


if __name__ == "__main__":
    unittest.main()
