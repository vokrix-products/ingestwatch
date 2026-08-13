# IngestWatch

IngestWatch is a backend ingestion service that monitors scheduled ingestion sources (GitHub Actions workflows, cron jobs, API syncs) and normalizes raw operational files into structured records. It is the input side of the Vokrix ingest-monitor platform.

## Archetype: Poller

IngestWatch is built as a poller. It accepts two kinds of input and returns normalized records:

1. **Source manifests** — JSON/CSV describing scheduled ingestion jobs; each source is evaluated and returned as a monitoring record with a severity status (missing, failed, empty, stale, flagged, or healthy).
2. **Raw file bytes** — contracts, supplier lists, pipeline exports, employee manifests; converted into a compact canonical shape that a downstream monitor can check.

It does not own storage, scheduling, or alerting.

## Canonical record shape

Every record returned by `process_file` / `process_sources` has at least:

- title: human-readable name of the source item
- status: normalized severity status

Additional fields from the source input are preserved when present, including due_date and raw source columns.

## Status normalization

Raw statuses are mapped to a small severity vocabulary:

- valid:good
- missing:critical
- expired:warning
- empty:warning
- flagged:warning
- failed:critical

## Source monitoring (monitor.py)

`process_sources(manifest)` accepts a JSON or CSV manifest of scheduled ingestion sources:

```json
{
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
      "qualified_count": 115
    }
  ]
}
```

Each source is evaluated against its schedule:

- no last run and the next run is due -> **missing:critical**
- last run failed or carries an error -> **failed:critical**
- run succeeded but fetched/qualified zero records -> **empty:warning**
- last run older than twice the expected interval -> **expired:warning**
- otherwise -> **valid:good**

Monitoring fields (fetched_count, scored_count, qualified_count, empty_run, last_run_at, next_run_at, schedule, workflow_id, repo_owner) are preserved on each record so dashboards can surface per-source health.

## File normalization (processor.py)

`process_file(file_bytes)` accepts raw file bytes. It tries parsers in order:

1. PDF via pdfplumber
2. Excel via openpyxl
3. UTF-8 text/CSV fallback
4. DeepSeek LLM extraction for unstructured single-text documents (only when DEEPSEEK_API_KEY is set)

Supported source layouts include CSV tables with headers like source_name, status, due_date, and plain text key-value documents such as:

```
Supplier: Acme Corp
Status: failed
Due Date: 2026-01-20
```

The normalizer also handles common business headers (Company, Organization, Business, Client, Title, Record, ...), falls back to the first non-empty column when no known title header exists, and groups plain-text blocks so a bare name line becomes the title of the key:value block that follows it.

## Requirements

Install dependencies with:

```
pip install -r requirements.txt
```

## Running

Run the demo (file normalization + source monitoring):

```
python3 run_demo.py
```

Run the test suite:

```
python3 run_tests.py
```

## Repository layout

- processor.py - file-to-records normalization engine
- monitor.py - source-manifest-to-monitoring-records engine
- poller.py - Supabase job poller (process_upload + process_sources)
- run_demo.py - zero-argument demo that prints JSON
- run_tests.py - unittest coverage for CSV, plain text, Excel, and source-manifest paths
