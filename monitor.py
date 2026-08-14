import csv
import io
import json
from datetime import datetime, timedelta, timezone

from processor import _normalize_date, _normalize_status

STATUS_FIELDS = ["status", "run_status", "source_status", "current_status", "health"]
FETCHED_FIELDS = ["fetched_count", "fetched", "fetch_count"]
SCORED_FIELDS = ["scored_count", "scored", "score_count"]
QUALIFIED_FIELDS = ["qualified_count", "qualified", "qual_count"]
EMPTY_FIELDS = ["empty_run", "is_empty", "empty"]
ERROR_FIELDS = ["error_message", "error", "run_error"]


def _parse_ts(raw):
    if not raw:
        return None
    val = str(raw).strip()
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        pass
    d = _normalize_date(val)
    if d:
        try:
            return datetime.fromisoformat(d)
        except ValueError:
            return None
    return None


def _count(row, fields):
    for f in fields:
        if f in row and row[f] not in (None, ""):
            try:
                return int(row[f])
            except (TypeError, ValueError):
                pass
    return None


def _flag(row, fields):
    for f in fields:
        if f in row:
            v = str(row[f]).strip().lower()
            if v in ("true", "1", "yes"):
                return True
    return False


def _schedule_interval_hours(schedule):
    """Crude cron -> expected interval in hours. Default 24."""
    if not schedule:
        return 24
    parts = str(schedule).split()
    if len(parts) >= 5:
        minute, hour, dom, month, dow = parts[:5]
        if dow not in ("*", "?"):
            return 24 * 7
        if dom not in ("*", "?"):
            return 24 * 30
        if "/" in hour:
            try:
                return max(1, int(hour.split("/")[1]))
            except ValueError:
                return 24
        if hour != "*":
            return 24
        if "/" in minute:
            try:
                return max(1, int(minute.split("/")[1]) // 60)
            except ValueError:
                return 24
        if minute != "*":
            return 1
    return 24


def _anomaly(fetched, scored, qualified):
    """Flagged detection: low scored/qualified throughput vs fetched."""
    if not fetched or fetched <= 0:
        return None
    if scored is not None and scored >= 0 and scored / fetched < 0.5:
        return "scored/fetched ratio {}/{} below 0.5".format(scored, fetched)
    if qualified is not None and qualified >= 0 and qualified / fetched < 0.3:
        return "qualified/fetched ratio {}/{} below 0.3".format(qualified, fetched)
    return None


def evaluate_source(row):
    """Turn one manifest row into a monitoring record with a normalized status."""
    if not row:
        return None
    now = datetime.now(timezone.utc)
    title = (
        row.get("source_name") or row.get("name") or row.get("title")
        or row.get("workflow_id") or row.get("repo") or "Untitled"
    )
    status_raw = row.get("status")
    last = _parse_ts(row.get("last_run_at"))
    next_run = _parse_ts(row.get("next_run_at"))
    fetched = _count(row, FETCHED_FIELDS)
    scored = _count(row, SCORED_FIELDS)
    qualified = _count(row, QUALIFIED_FIELDS)
    empty_flag = _flag(row, EMPTY_FIELDS)
    error = row.get("error_message") or row.get("error")

    status = None
    alert_reason = None
    # 1. Explicit non-valid status in the manifest wins
    norm = _normalize_status(status_raw) if status_raw else None
    if norm and norm != "valid:good":
        status = norm
        alert_reason = "Reported status: {}".format(status_raw)
    # 2. Error message on the run -> failed.
    if status is None and error:
        status = "failed:critical"
        alert_reason = "Run failed: {}".format(error)
    # 3. Empty run: flagged empty or zero records fetched.
    if status is None and (empty_flag or (fetched is not None and fetched == 0)):
        status = "empty:warning"
        alert_reason = "Empty run: 0 records fetched from {}".format(title)
    # 4. Anomaly: low scored/qualified throughput -> flagged.
    if status is None:
        anomaly = _anomaly(fetched, scored, qualified)
        if anomaly:
            status = "flagged:warning"
            alert_reason = "Flagged: {}".format(anomaly)
    # 5. Reported counts are positive evidence the source ran fine.
    if status is None and fetched is not None and fetched > 0:
        status = "valid:good"
    # 6. No last run and the next run is due (or unknown) -> missing.
    if status is None and last is None:
        if next_run is None or next_run <= now:
            status = "missing:critical"
            alert_reason = "No run record found and next run is due"
    # 7. Last run older than twice the expected interval -> expired.
    if status is None and last is not None:
        interval = _schedule_interval_hours(row.get("schedule"))
        if now - last > timedelta(hours=interval * 2):
            status = "expired:warning"
            age_h = int((now - last).total_seconds() // 3600)
            alert_reason = "Stale: last run {}h ago (expected <= {}h)".format(age_h, int(interval * 2))
    # 8. Otherwise healthy.
    if status is None:
        status = "valid:good"

    record = {"title": title, "status": status}
    if next_run:
        record["due_date"] = next_run.date().isoformat()
    if status != "valid:good" and alert_reason:
        record["alert_reason"] = alert_reason
    if status == "empty:warning" or (fetched is not None and fetched == 0):
        record["empty_run"] = True
    for key, value in row.items():
        if key not in ("title", "status", "due_date"):
            record[key] = value
    return record


def process_sources(manifest):
    """Accept a JSON/CSV source manifest (str, bytes, or list) and return
    normalized monitoring records."""
    if isinstance(manifest, bytes):
        try:
            manifest = manifest.decode("utf-8-sig")
        except UnicodeDecodeError:
            return []
    if isinstance(manifest, str):
        text = manifest.strip()
        if not text:
            return []
        if text.startswith(("{", "[")):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return []
            rows = data.get("sources", []) if isinstance(data, dict) else data
            if isinstance(rows, dict):
                rows = [rows]
        else:
            reader = csv.DictReader(io.StringIO(text))
            rows = [row for row in reader if row and any((v or "").strip() for v in row.values())]
    elif isinstance(manifest, list):
        rows = manifest
    else:
        rows = []
    return [r for r in (evaluate_source(row) for row in rows if isinstance(row, dict) and row) if r]
