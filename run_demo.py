import csv
import io
import json
from processor import process_file

def main():
    rows = [{"source_name": "stripe", "status": "running", "due_date": "2026-01-15"}, {"source_name": "salesforce", "status": "failed", "due_date": "2026-01-16", "error_message": "timeout"}]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["source_name", "status", "due_date", "error_message"])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    records = process_file(buf.getvalue().encode("utf-8"))
    assert isinstance(records, list)
    assert len(records) == len(rows)
    print(json.dumps(records, indent=2))

if __name__ == "__main__":
    main()
