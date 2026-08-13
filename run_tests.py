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


if __name__ == "__main__":
    unittest.main()
