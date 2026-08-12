import csv
import io
import json
import os
import re
from datetime import datetime

import openpyxl
import pdfplumber
from openai import OpenAI

STATUS_VALUES = [
    "valid:good",
    "missing:critical",
    "expired:warning",
    "empty:warning",
    "flagged:warning",
    "failed:critical",
]

TITLE_FIELDS = [
    "source_name", "source", "name", "supplier", "vendor_name",
    "vendor", "employee_name", "employee", "patient_name", "patient",
    "contract_party", "client_name", "customer_name", "repo_name",
    "account_name"
]

STATUS_FIELDS = ["status", "run_status", "pipeline_status", "source_status"]
EMPTY_RUN_FIELDS = ["empty_run", "is_empty", "empty"]
FETCHED_COUNT_FIELDS = ["fetched_count", "fetch_count", "fetched"]
ERROR_FIELDS = ["error_message", "error", "run_error", "message"]
DATE_FIELDS = ["due_date", "next_run_at", "date_due", "due", "deadline", "expires_at", "expiry_date"]

_STATUS_SYNONYMS = {
    "ok": "valid:good", "success": "valid:good", "successful": "valid:good",
    "valid": "valid:good", "good": "valid:good", "passed": "valid:good",
    "pass": "valid:good", "healthy": "valid:good", "running": "valid:good",
    "failed": "failed:critical", "failure": "failed:critical", "error": "failed:critical",
    "missing": "missing:critical", "not_found": "missing:critical",
    "expired": "expired:warning", "overdue": "expired:warning",
    "empty": "empty:warning", "blank": "empty:warning",
    "flagged": "flagged:warning", "warning": "flagged:warning",
}


def _normalize_status(raw):
    if not raw:
        return "empty:warning"
    val = str(raw).strip().lower()
    if val in _STATUS_SYNONYMS:
        return _STATUS_SYNONYMS[val]
    if val in STATUS_VALUES:
        return val
    if "fail" in val or "error" in val or "missing" in val:
        return "failed:critical"
    if "expired" in val or "overdue" in val:
        return "expired:warning"
    if "empty" in val or "blank" in val:
        return "empty:warning"
    if "flag" in val or "warn" in val:
        return "flagged:warning"
    if "valid" in val or "ok" in val or "pass" in val or "good" in val or "success" in val:
        return "valid:good"
    return "valid:good"


def _normalize_date(raw):
    if not raw:
        return None
    val = str(raw).strip()
    if not val:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    patterns = [
        "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
        "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%Y%m%d",
    ]
    for pattern in patterns:
        try:
            return datetime.strptime(val, pattern).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", val)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def _pick_field(row, fields):
    for field in fields:
        if field in row:
            return row[field]
    for key, value in row.items():
        if key and re.sub(r"[^a-z]", "", key.lower()) in fields:
            return value
    return None


def _records_from_dicts(rows):
    records = []
    for row in rows:
        if not row:
            continue
        title = _pick_field(row, TITLE_FIELDS)
        status_raw = _pick_field(row, STATUS_FIELDS)
        due_raw = _pick_field(row, DATE_FIELDS)
        status = _normalize_status(status_raw)
        due = _normalize_date(due_raw)
        record = {"title": str(title) if title else None, "status": status}
        if due:
            record["due_date"] = due
        for key, value in row.items():
            if key not in ("title", "status", "due_date"):
                record[key] = value
        records.append(record)
    return records


def _parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader]
    if not rows:
        return []
    return _records_from_dicts(rows)


def _parse_plain_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    current = {}
    for line in lines:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", line):
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()
        else:
            if current:
                rows.append(current)
                current = {}
            rows.append({"name": line})
    if current:
        rows.append(current)
    if not rows:
        return []
    return _records_from_dicts(rows)


def _parse_pdf(file_bytes):
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if not text.strip():
        return []
    return _parse_plain_text(text)


def _parse_excel(file_bytes):
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    rows = []
    for ws in wb.worksheets:
        data = list(ws.iter_rows(values_only=True))
        if not data:
            continue
        header = [str(c).strip() if c is not None else "" for c in data[0]]
        for raw_row in data[1:]:
            row = {header[i]: raw_row[i] for i in range(min(len(header), len(raw_row)))}
            if any(v is not None and str(v).strip() for v in row.values()):
                rows.append(row)
    return _records_from_dicts(rows)


def _deepseek_extract(text):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return []
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Extract records as JSON array with keys title, status, due_date. Return only JSON."},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("records", [data])
        return _records_from_dicts([d for d in data if isinstance(d, dict)])
    except Exception:
        return []


def process_file(file_bytes):
    if not isinstance(file_bytes, bytes):
        raise TypeError("file_bytes must be bytes")
    records = []
    # PDF first
    try:
        records = _parse_pdf(file_bytes)
    except Exception:
        records = []
    # Excel
    if not records:
        try:
            records = _parse_excel(file_bytes)
        except Exception:
            records = []
    # Text/CSV fallback
    if not records:
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return []
        if any(line.strip() for line in text.splitlines()):
            records = _parse_csv(text)
        if not records:
            records = _parse_plain_text(text)
    # DeepSeek fallback for unstructured single-text docs
    if not records:
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = ""
        if text.strip():
            records = _deepseek_extract(text)
    return records
