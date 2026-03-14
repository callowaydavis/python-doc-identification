# Document Processing Pipeline

A 4-script Python pipeline that inventories documents, OCRs them page-by-page, ingests labeled sample documents, and identifies where known document types appear inside larger files using TF-IDF cosine similarity.

## How It Works

| Script | Purpose |
|--------|---------|
| `01_inventory.py` | Walk a directory and register all PDF/TIFF files in the database |
| `02_ocr_processor.py` | Pick pending documents, OCR each page, and store the extracted text |
| `03_ingest_sample.py` | OCR labeled sample documents (single file or folder) to represent a known document type |
| `04_match_documents.py` | Match inventory pages against samples to identify document types |
| `05_feedback.py` | Flag false-positive matches and tune per-type thresholds automatically |
| `06_extract_subdocuments.py` | Extract matched page ranges from parent files into individual PDFs |
| `07_keywords.py` | Add, update, remove, and list per-type keyword boosts and penalties |

---

## Prerequisites

### Python

Python 3.10 or later is required (the code uses the `X | Y` union type syntax).

### System Dependencies (macOS)

Install via [Homebrew](https://brew.sh):

```bash
brew install tesseract   # OCR engine
brew install poppler     # PDF rendering (required by pdf2image)
```

### Microsoft ODBC Driver for SQL Server

Required for database connectivity. Install **ODBC Driver 17 or 18**:

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18
```

> If you install Driver 17 instead, update `DB_DRIVER` in your `.env` file accordingly.

For other platforms, see the [Microsoft installation docs](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server).

### SQL Server

A running SQL Server instance is required. SQL Server 2017+ or Azure SQL Database are both supported.

---

## Installation

### 1. Clone / download the project

```bash
cd /Users/jake/python-app
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# SQL Server connection
DB_SERVER=localhost          # hostname or IP of your SQL Server
DB_PORT=1433                 # default SQL Server port
DB_NAME=document_pipeline    # database name (must already exist)
DB_USER=sa                   # SQL Server login
DB_PASSWORD=your_password    # SQL Server password
DB_DRIVER=ODBC Driver 18 for SQL Server   # must match your installed driver

# Pipeline tuning (optional — these are the defaults)
SIMILARITY_THRESHOLD=0.35   # minimum cosine similarity to record a match (0.0–1.0)
OCR_DPI=300                  # DPI used when rendering PDFs to images
TESSERACT_LANG=eng           # Tesseract language pack(s), e.g. "eng+fra"
```

> `.env` is gitignored and will never be committed.

### 5. Create the database tables

Connect to your SQL Server instance and run `db/schema.sql` to create all required tables:

```bash
# Using sqlcmd (adjust connection flags as needed)
sqlcmd -S localhost -U sa -P your_password -d document_pipeline -i db/schema.sql
```

Or open `db/schema.sql` in SQL Server Management Studio (SSMS) / Azure Data Studio and execute it.

This creates five tables: `documents`, `document_pages`, `sample_documents`, `sample_pages`, and `document_matches`.

To enable feedback tracking, also run `db/schema_feedback.sql`:

```bash
sqlcmd -S localhost -U sa -P your_password -d document_pipeline -i db/schema_feedback.sql
```

To enable keyword boosts/penalties, also run `db/schema_keywords.sql`:

```bash
sqlcmd -S localhost -U sa -P your_password -d document_pipeline -i db/schema_keywords.sql
```

---

## Running the Pipeline

All scripts are run from the project root with the virtual environment active.

### Step 1 — Inventory documents

Scan a directory recursively for `.pdf`, `.tif`, and `.tiff` files and register them in the database.

```bash
python scripts/01_inventory.py /path/to/your/documents
```

Output example:
```
Scanning: /path/to/your/documents
Found: 42  |  New: 42  |  Already known: 0
```

The script is safe to re-run — existing records are not duplicated.

---

### Step 2 — OCR documents

Process pending documents one at a time, or loop until the queue is empty.

```bash
# Process one document
python scripts/02_ocr_processor.py

# Process all pending documents
python scripts/02_ocr_processor.py --loop
```

Each document's status moves through `pending → processing → complete` (or `error` on failure). If an error occurs, the message is stored in the `documents.ocr_error` column and processing continues with the next document.

#### Running Multiple Workers

To speed up OCR, you can run several instances of `02_ocr_processor.py` simultaneously across multiple servers or terminals. Workers self-coordinate through the database — no message broker or other infrastructure is needed.

**Setup (once):** run the migration to add the worker tracking column:

```bash
sqlcmd -S localhost -U sa -P your_password -d document_pipeline -i db/schema_ocr_workers.sql
```

**Start workers** — each server runs independently:

```bash
python scripts/02_ocr_processor.py --loop
```

Each worker records its `hostname:PID` in the database when it claims a document, so you can see which server holds which document at any time.

**Crash recovery:** if a worker is killed mid-processing, the document it held stays in `'processing'` state. The next time any healthy worker polls, it automatically resets documents that have been stuck longer than `OCR_STALE_MINUTES` back to `'pending'` so they are reprocessed.

**Tip:** lower `OCR_DPI` (e.g., `OCR_DPI=150`) for a significant throughput improvement at a modest quality cost.

---

### Step 3 — Ingest sample documents

Provide labeled example files so the matcher knows what each document type looks like. You can pass either a single file or a folder. When a folder is given, every PDF/TIFF inside it is ingested under the same document type label.

```bash
# Single file
python scripts/03_ingest_sample.py /path/to/sample.pdf "Document Type Label"

# Entire folder — all PDFs/TIFFs inside are ingested as the same type
python scripts/03_ingest_sample.py /path/to/samples/invoices/ "Invoice"
```

Examples:
```bash
python scripts/03_ingest_sample.py samples/invoices/ "Invoice"
python scripts/03_ingest_sample.py samples/w2_sample.pdf "W-2"
python scripts/03_ingest_sample.py samples/lease_agreements/ "Lease Agreement"
```

The script is idempotent — files already in the database are skipped, so it's safe to re-run.

---

### Step 4 — Match documents

Compare every page of every OCR'd inventory document against the sample corpus and write matches to `document_matches`.

```bash
# Match all unmatched documents (safe to re-run — skips already-matched docs)
python scripts/04_match_documents.py

# Match a single document by ID
python scripts/04_match_documents.py --document-id 7

# Re-match everything, replacing all existing matches
python scripts/04_match_documents.py --regen
```

Output example:
```
Loading sample pages...
Fitting TF-IDF on 12 sample pages...
Matching 42 document(s)...
  doc 1: Invoice p1-2 (0.71), Lease Agreement p5-8 (0.52)
  doc 2: no matches above threshold 0.35
  ...
Done. 38 match record(s) written.
```

Results are stored in `document_matches` with:
- The document type identified
- The page range within the inventory document
- A `confidence_score` (0.0–1.0, mean cosine similarity across the matched page run)
- The best-matching sample page reference

---

### Step 5 — Record feedback and tune thresholds

When you spot a false match in `document_matches`, flag it so Script 04 will suppress similar matches in future runs.

```bash
# Flag match 42 as a false positive
python scripts/05_feedback.py --match-id 42

# Flag with an explanatory note
python scripts/05_feedback.py --match-id 42 --note "This is a receipt, not an invoice"

# Review per-type stats and recommended thresholds before re-running Script 04
python scripts/05_feedback.py --report

# List all recorded feedback
python scripts/05_feedback.py --list
```

Example `--report` output:
```
Document Type        | False Matches | Score Range      | Recommended Threshold | Current
---------------------|---------------|------------------|-----------------------|--------
Invoice              |             4 | 0.38 – 0.54      |                  0.59 |    0.35
Lease Agreement      |             1 | 0.41 – 0.41      |                  0.46 |    0.35

Excluded sample pages (≥3 false matches):
  sample_id=7, page=2  (4 false matches) — type: Invoice
```

After recording feedback, re-run Script 04 to apply the adjusted thresholds:

```bash
python scripts/04_match_documents.py --regen --document-id N
# or to re-match all documents:
python scripts/04_match_documents.py --regen
```

Script 04 reads `match_feedback` on every run and automatically:
- Raises the per-type threshold to `max_false_positive_score + FEEDBACK_PENALTY`
- Excludes from the TF-IDF corpus any sample page with ≥ `SAMPLE_PAGE_EXCLUSION_COUNT` false-match records

---

### Step 7 — Manage keyword boosts and penalties

Fine-tune matching scores by adding per-type keywords. A positive weight boosts the score when the keyword appears in a page; a negative weight penalizes it. Adjusted scores are clamped to the range [0.0, 1.5].

```bash
# Boost pages that contain "amount due" when matching as Invoice
python scripts/07_keywords.py --add --type "Invoice" --keyword "amount due" --weight 0.15

# Penalize Invoice matches when a competing term appears
python scripts/07_keywords.py --add --type "Invoice" --keyword "deposit slip" --weight -0.20

# Re-running --add with a new weight safely updates the existing entry
python scripts/07_keywords.py --add --type "Invoice" --keyword "amount due" --weight 0.25

# Remove by ID
python scripts/07_keywords.py --remove --keyword-id 5

# List all keywords
python scripts/07_keywords.py --list

# List keywords for one type
python scripts/07_keywords.py --list --type "Invoice"
```

Example `--list` output:
```
ID  Type                  Keyword              Weight
--  --------------------  -------------------  ------
 1  Invoice               amount due           +0.150
 2  Invoice               deposit slip         -0.200
 3  Lease Agreement       lease term           +0.100
```

After adding or changing keywords, re-run Script 04 to apply them:

```bash
python scripts/04_match_documents.py --regen
```

---

### Step 6 — Extract subdocument PDFs

Once matches are confirmed, extract each matched subdocument into its own PDF file. Multiple match segments of the same document type from the same parent file are automatically combined into one output PDF in page order.

```bash
# Extract all matched subdocuments into ./output/extracted/
python scripts/06_extract_subdocuments.py

# Write to a custom directory
python scripts/06_extract_subdocuments.py --output-dir /path/to/output

# Limit to one source document
python scripts/06_extract_subdocuments.py --document-id 7

# Limit to one document type
python scripts/06_extract_subdocuments.py --document-type "Invoice"
```

Output files are organized by document type and named after their source document:

```
output/
  extracted/
    Invoice/
      doc_7_Invoice.pdf        ← pages 1-2 and 15-16 combined (two match segments)
    Lease_Agreement/
      doc_7_Lease_Agreement.pdf
      doc_12_Lease_Agreement.pdf
```

Example output:
```
Loading matches...
Found 3 subdocument(s) to extract across 2 source file(s).

  doc 7 / Invoice — pages 1-2, 15-16 (2 segments combined)
    → output/extracted/Invoice/doc_7_Invoice.pdf
  doc 7 / Lease Agreement — pages 5-8 (1 segment)
    → output/extracted/Lease_Agreement/doc_7_Lease_Agreement.pdf
  doc 12 / Lease Agreement — pages 3-6 (1 segment)
    → output/extracted/Lease_Agreement/doc_12_Lease_Agreement.pdf

Done. 3 file(s) written, 0 error(s).
```

PDF sources are extracted using `pypdf` (vector quality preserved). TIFF sources are extracted frame-by-frame and saved as PDF using Pillow.

---

## Project Structure

```
.
├── config.py                  # DB connection + tunable constants
├── .env                       # Secrets — fill this in (gitignored)
├── .env.example               # Template for .env
├── requirements.txt
├── db/
│   ├── connection.py          # pyodbc context manager
│   ├── schema.sql             # DDL — run once against SQL Server
│   ├── schema_feedback.sql    # DDL — adds match_feedback table
│   ├── schema_keywords.sql    # DDL — adds type_keywords table
│   └── schema_ocr_workers.sql # DDL — adds worker_id column for multi-worker support
├── scripts/
│   ├── 01_inventory.py
│   ├── 02_ocr_processor.py
│   ├── 03_ingest_sample.py
│   ├── 04_match_documents.py
│   ├── 05_feedback.py
│   ├── 06_extract_subdocuments.py
│   └── 07_keywords.py         # Manage per-type keyword boosts/penalties
├── output/
│   └── extracted/             # Default output for Script 06 (gitignored)
└── utils/
    ├── ocr.py                 # Shared OCR logic (pdf2image + pytesseract)
    └── text_utils.py          # Text cleaning helpers
```

---

## Configuration Reference

All settings are controlled via `.env`. Only `DB_*` values are required; the rest have defaults.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_SERVER` | Yes | — | SQL Server hostname or IP |
| `DB_PORT` | No | `1433` | SQL Server port |
| `DB_NAME` | Yes | — | Target database name |
| `DB_USER` | Yes | — | SQL login username |
| `DB_PASSWORD` | Yes | — | SQL login password |
| `DB_DRIVER` | No | `ODBC Driver 18 for SQL Server` | Installed ODBC driver name |
| `SIMILARITY_THRESHOLD` | No | `0.35` | Minimum score to record a match |
| `FEEDBACK_PENALTY` | No | `0.05` | Added to the highest false-positive score to compute per-type threshold |
| `SAMPLE_PAGE_EXCLUSION_COUNT` | No | `3` | False-match count at which a sample page is dropped from the corpus |
| `OCR_DPI` | No | `300` | PDF render resolution |
| `TESSERACT_LANG` | No | `eng` | Tesseract language(s) |
| `OCR_STALE_MINUTES` | No | `60` | Minutes before a stuck `'processing'` document is reset to `'pending'` (multi-worker crash recovery) |
| `TFIDF_STOP_WORDS` | No | _(none)_ | Set to `english` to strip common words from the TF-IDF vocabulary |
| `TFIDF_MAX_DF` | No | `1.0` | Drop tokens that appear in more than this fraction of a type's sample pages |
| `TFIDF_MIN_DF` | No | `1` | Drop tokens that appear in fewer than this many of a type's sample pages |
| `TFIDF_NGRAM_MAX` | No | `2` | Upper bound of the n-gram range; `(1, N)` means unigrams through N-grams |
| `TFIDF_MAX_FEATURES` | No | _(unlimited)_ | Cap vocabulary size per type; omit or leave blank for no cap |
| `TFIDF_MIN_TYPE_SAMPLES` | No | `3` | Warn when a type has fewer than this many sample pages |

---

## Troubleshooting

**`tesseract: command not found`**
Install Tesseract via Homebrew: `brew install tesseract`

**`pdf2image` errors / blank pages**
Poppler must be installed: `brew install poppler`

**`pyodbc` connection errors**
- Verify the ODBC driver name in `.env` exactly matches what is installed. Run `odbcinst -q -d` (Linux/macOS) to list installed drivers.
- Confirm SQL Server is reachable: `sqlcmd -S $DB_SERVER -U $DB_USER -P $DB_PASSWORD -Q "SELECT 1"`
- If using a self-signed certificate, `TrustServerCertificate=yes` is already set in `config.py`.

**Low match confidence / no matches**
- Lower `SIMILARITY_THRESHOLD` in `.env` (e.g., `0.20`) and re-run Script 4 with `--regen`.
- Ensure sample documents are representative, clean, and text-rich.
- Check that OCR completed successfully (`ocr_status = 'complete'`) and pages have reasonable `word_count` values.
