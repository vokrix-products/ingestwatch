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

# Known title-bearing column names. _pick_field also matches keys after
# stripping spaces/punctuation, so entries include normalized aliases
# (e.g. "companyname" matches "Company Name").
TITLE_FIELDS = [
    "source_name", "source", "name", "supplier", "vendor_name",
    "vendor", "employee_name", "employee", "patient_name", "patient",
    "contract_party", "client_name", "customer_name", "repo_name",
    "account_name",
    "company", "company_name", "companyname",
    "organization", "organisation", "organization_name", "organisation_name",
    "organizationname", "organisationname",
    "business", "business_name", "businessname",
    "name_of_business", "nameofbusiness",
    "client", "clientname", "customer", "customername",
    "title", "record_title", "recordtitle", "record", "record_name",
    "recordname", "name_of_record", "nameofrecord",
    "item", "item_name", "itemname",
    "product", "product_name", "productname",
    "project", "project_name", "projectname",
    "contract", "contract_name", "contractname",
    "document", "document_name", "documentname",
    "entity", "entity_name", "entityname", "legal_name", "legalname",
    "trading_name", "tradingname", "filename", "file_name",
]

STATUS_FIELDS = [
    "status", "run_status", "pipeline_status", "source_status",
    "runstatus", "pipelinestatus", "sourcestatus",
    "current_status", "currentstatus",
]
EMPTY_RUN_FIELDS = ["empty_run", "is_empty", "empty", "emptyrun", "isempty"]
FETCHED_COUNT_FIELDS = [
    "fetched_count", "fetch_count", "fetched", "fetchedcount", "fetchcount",
]
ERROR_FIELDS = ["error_message", "error", "run_error", "message", "errormessage", "runerror"]
DATE_FIELDS = [
    "due_date", "next_run_at", "date_due", "due", "deadline",
    "expires_at", "expiry_date", "duedate", "nextrunat", "expirydate",
    "expiresat", "completed_at", "created_at", "updated_at",
    "completedat", "createdat", "updatedat",
]

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


# Keys that should never be used as a title fallback source.
_SKIP_TITLE_KEYS = {
    "status", "runstatus", "pipelinestatus", "sourcestatus", "currentstatus",
    "state", "result", "results",
    "duedate", "nextrunat", "datedue", "due", "deadline", "expiresat",
    "expirydate", "date", "createdat", "updatedat", "completedat",
    "timestamp", "time",
    "fetchedcount", "fetchcount", "fetched", "count", "total", "rowcount",
    "recordcount", "numrecords", "numrows",
    "errormessage", "error", "runerror", "message", "notes", "note",
    "comment", "comments", "description", "details", "summary",
    "id", "uuid", "recordid", "jobid", "customerid", "productid", "userid",
    "sourcefilepath", "filepath", "bucket", "path", "url", "link",
    "filename", "file",
    "empty", "isempty", "emptyrun", "type", "category", "categoryname",
    "priority", "severity", "owner", "assignee", "assignedto",
    "department", "team", "location", "region",
    "createdby", "updatedby", "modifiedat", "modifiedby", "publishedat",
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


def _fallback_title(row):
    """Pick the first non-empty cell that is not metadata/status/date noise."""
    for key, value in row.items():
        if not key or _skip_title_key(key):
            continue
        v = str(value).strip() if value is not None else ""
        if not v:
            continue
        if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", v):
            continue
        return v[:200]
    return None


def _skip_title_key(key):
    normalized = re.sub(r"[^a-z]", "", key.lower())
    return normalized in _SKIP_TITLE_KEYS


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
        if not title:
            title = _fallback_title(row)
        record = {"title": str(title) if title else None, "status": status}
        if due:
            record["due_date"] = due
        for key, value in row.items():
            if key not in ("title", "status", "due_date"):
                record[key] = value
        records.append(record)
    return records


def _parse_csv(text):
    sample = text.strip().splitlines()
    if not sample:
        return []
    # Only treat text as CSV when a real delimiter is present in the header.
    # Without this guard, bare-word plain text ("Acme Corp\nGlobex") would be
    # misread as single-column rows with the first line as header.
    if not any(d in sample[0] for d in (",", "\t", ";")):
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader if row and any((v or "").strip() for v in row.values())]
    if not rows:
        return []
    return _records_from_dicts(rows)



def _parse_markdown_table(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines or not all(l.startswith("|") for l in lines[:2]):
        return []
    data_lines = []
    for line in lines:
        if not line.startswith("|"): continue
        if re.match(r"^\|[\s:\-|]+\|$", line): continue
        data_lines.append(line)
    if len(data_lines) < 2: return []
    header = [p.strip() for p in data_lines[0].strip().strip("|").split("|")]
    rows = []
    for line in data_lines[1:]:
        cells = [p.strip() for p in line.strip().strip("|").split("|")]
        row = {header[i]: cells[i] for i in range(min(len(header), len(cells)))}
        if any(v for v in row.values()): rows.append(row)
    return _records_from_dicts(rows) if rows else []


def _parse_plain_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    current = {}
    pending_name = None
    kv_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_ ]*?)\s*:\s*(.*)$")
    for line in lines:
        m = kv_re.match(line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            # A repeated known key (e.g. another "Status") means the previous
            # block is finished and a new record has started.
            if key.lower() in current:
                rows.append(current)
                current = {}
            if pending_name is not None:
                current.setdefault("name", pending_name)
                pending_name = None
            current[key] = value
        else:
            # Bare line: flush any open block, then treat the line as the name
            # (title) of the following key:value block. Consecutive bare lines
            # each become their own record.
            if current:
                rows.append(current)
                current = {}
            if pending_name is not None:
                rows.append({"name": pending_name})
            pending_name = line
    if current:
        rows.append(current)
    elif pending_name is not None:
        rows.append({"name": pending_name})
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
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": (
                    "Extract records as a JSON array of objects with keys "
                    "title, status, due_date. Use the source/company/entity name "
                    "as the title. Return only JSON."
                )},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=2000,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("records", [data])
        return _records_from_dicts([d for d in data if isinstance(d, dict)])
    except Exception:
        return []


def _records_are_noise(records):
    """True when none of the parsed records carry a usable title."""
    return not records or not any(r.get("title") for r in records)


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
            text = ""
        if any(line.strip() for line in text.splitlines()):
            records = _parse_csv(text)
        if not records:
            records = _parse_plain_text(text)
    # DeepSeek rescue: deterministic parsers produced only title-less noise
    # (e.g. unrecognized headers) -> let the LLM extract real records.
    if _records_are_noise(records):
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = ""
        if text.strip():
            llm_records = _deepseek_extract(text)
            if llm_records:
                records = llm_records
    # DeepSeek fallback for unstructured single-text documents.
    if not records:
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = ""
        if text.strip():
            records = _deepseek_extract(text)
    return records
