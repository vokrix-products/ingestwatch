# IngestWatch

IngestWatch is a backend ingestion service that normalizes raw operational files into structured records. It is the input side of the Vokrix ingest-monitor platform.

## Archetype: Poller

IngestWatch is built as a poller. It accepts file bytes and returns normalized records. It does not own storage, scheduling, or alerting. It converts messy source data (contracts, supplier lists, pipeline exports, employee manifests) into a compact canonical shape that a downstream monitor can check.

## Canonical record shape

Every record returned by process_file has at least:

- title: human-readable name of the source item
- status: normalized severity status

Additional fields from the source file are preserved when present, including due_date and raw source columns.

## Status normalization

Raw statuses are mapped to a small severity vocabulary:

- valid:good
- missing:critical
- expired:warning
- empty:warning
- flagged:warning
- failed:critical

## What the poller expects as input

process_file(file_bytes) accepts raw file bytes. It tries parsers in order:

1. PDF via pdfplumber
2. Excel via openpyxl
3. UTF-8 text/CSV fallback
4. DeepSeek LLM extraction for unstructured single-text documents (only when DEEPSEEK_API_KEY is set)

Supported source layouts include CSV tables with headers like source_name, status, due_date, and plain text key-value documents such as:

Supplier: Acme Corp
Status: failed
Due Date: 2026-01-20

## Requirements

Install dependencies with:

pip install -r requirements.txt

## Running

Run the demo:

python3 run_demo.py

Run the test suite:

python3 run_tests.py

## Repository layout

- processor.py - file-to-records normalization engine
- run_demo.py - zero-argument demo that prints JSON
- run_tests.py - unittest coverage for CSV, plain text, and Excel paths

## Live URLs
Dashboard: https://ingestwatch.vokrix.co
Vercel Project: ingestwatch
Railway Service ID: b916b524-ad1e-4673-b78e-e209b7e0554b
