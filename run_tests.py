import csv
import io
import unittest

from processor import STATUS_VALUES, process_file


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
