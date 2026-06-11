# TIP ESG Platform

A Streamlit-based ESG data collection and benchmarking platform for the
Tire Industry Project (TIP), built by dss+. Supports multi-company KPI
submission, verification workflows, benchmarking, and PDF reporting.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Build the master database (first run only)
python scripts/build_esg_master.py

# 3. Launch the app
streamlit run app.py
```

## Project Structure

```
esg/
│
├── app.py                        # Entry point: routing, session state, global init
├── config.py                     # All constants, secrets, year bounds, auth config
├── data_loader.py                # CSV read helpers (swap to Azure SQL on migration)
├── formula_engine.py             # KPI calculations and emission factor logic
├── storage.py                    # Storage client (local CSV; Azure-ready interface)
├── ui_components.py              # CSS, HTML card builders, chart layout defaults
│
├── pages/                        # One module per nav page (imported by app.py)
│   ├── page_home.py              # Client home dashboard
│   ├── page_my_records.py        # Client template view + Submit & Save
│   ├── page_my_dashboard.py      # Sector comparison charts
│   ├── page_benchmarking.py      # KPI benchmarking tabs + PDF download
│   ├── page_analysis.py          # DSS cross-company analysis charts
│   ├── page_reports.py           # PDF report generation
│   ├── page_verification.py      # DSS verification queue (Accept/Seen/Reject)
│   ├── page_company_data.py      # DSS full-template view for any company
│   ├── page_portfolio.py         # DSS portfolio overview
│   ├── page_readiness.py         # Submission readiness scoring
│   ├── page_doc_library.py       # Document library
│   ├── page_admin.py             # Admin / tenant management
│   └── page_settings.py          # User settings
│
├── components/                   # Shared UI blocks used by multiple pages
│   ├── render_template_table.py  # Main KPI template (editable + Comments column)
│   ├── render_electricity_tab.py # Electricity by country editor
│   ├── render_waste_tab.py       # Waste data section
│   ├── render_people_tab.py      # People & Governance section
│   ├── render_qualitative_tab.py # Qualitative data section
│   └── render_conversion_tab.py  # Conversion tables section
│
├── utils/                        # Pure logic helpers (no Streamlit dependency)
│   └── comment_utils.py          # Field-level comment workflow (save/load/approve)
│
├── pdf/                          # PDF generation
│   ├── pdf_report.py             # Executive one-page PDF report
│   └── pdf_charts_v2.py          # Matplotlib chart builders for PDF embedding
│
├── ai/                           # AI / LLM features
│   └── llm_client.py             # Azure OpenAI client (anonymised KPI summaries only)
│
├── scripts/                      # Standalone ops scripts — not imported by app.py
│   ├── build_esg_master.py       # One-time: builds master CSV from consolidated Excel
│   └── tip_progress_report.py    # TIP sector progress report generator
│
└── data_storage/                 # Local data (replaced by Azure SQL + Blob on migration)
    ├── master/                   # Master wide CSV (one row per company per year)
    ├── versions/                 # Parquet snapshots per save event (audit trail)
    ├── members/
    │   ├── TIP/                  # Per-company CSVs for TIP members
    │   └── non_TIP/              # Per-company CSVs for non-TIP members
    ├── reports/TIP/              # Generated PDF reports
    ├── chat_logs/                # AI chatbot usage logs (JSONL)
    └── validated/                # DSS-validated submission snapshots
```

## Authentication

- **Clients** log in with their company email (e.g. `verdatyres@tip-reporting.com`)
- **DSS+ Analysts** log in with `@consultdss.com` email
- In production, set `CLIENTS_JSON` and `DSS_EMAIL_DOMAIN` in `.streamlit/secrets.toml`
- Azure AD integration is scaffolded in `ai/llm_client.py` and `storage.py`

## Configuration

All settings are in `config.py` and can be overridden via `.streamlit/secrets.toml`
or environment variables:

| Key | Default | Purpose |
|-----|---------|---------|
| `DATA_YEAR_START` | `2009` | First year in dataset |
| `DATA_YEAR_END` | `2023` | Latest year (auto-detected from data) |
| `DSS_EMAIL_DOMAIN` | `@consultdss.com` | DSS employee email suffix |
| `CLIENTS_JSON` | demo dict | JSON map of email → company name |
| `AZURE_OPENAI_KEY` | `""` | Azure OpenAI API key for AI features |
| `FILELOCK_TIMEOUT` | `10` | Seconds to wait for CSV file lock |

## Azure Migration Guide

The platform is designed to swap the local file storage for Azure services
with minimal code changes:

| Current | Azure target |
|---------|-------------|
| `data_storage/master/*.csv` | Azure SQL `master_data` table |
| `data_storage/versions/*.parquet` | Azure SQL `versions` table + Blob Storage |
| `data_storage/field_comments.csv` | Azure SQL `comments` table |
| `data_storage/reports/` | Azure Blob Storage |
| Client dict in `config.py` | Azure Active Directory |
| `storage.py` LocalStorage | Replace with Azure SDK client |

Key files to update: `data_loader.py` (swap `pd.read_csv` → `pd.read_sql`),
`utils/comment_utils.py` (swap CSV read/write → SQL INSERT/UPDATE),
`storage.py` (swap file ops → Blob SDK).

## Requirements

```
streamlit>=1.35.0
pandas>=2.0.0
numpy>=1.24.0
plotly>=5.18.0
reportlab>=4.0.0
matplotlib>=3.7.0
openpyxl>=3.1.0
pyarrow>=14.0.0
filelock>=3.13.0
msal>=1.28.0
requests>=2.31.0
python-dotenv>=1.0.0
```

## Key Design Decisions

- **No kaleido** — PDF charts use matplotlib (Agg backend) instead of Plotly image export,
  so no system-level chrome/kaleido dependency is needed
- **Single master CSV** — all companies in one file; per-company CSVs are derived outputs
  only, not the source of truth
- **Year-bound config** — `DATA_YEAR_END` is detected from data at startup via
  `config.refresh_year_bounds()` — no hardcoded years in page logic
- **Comment versioning** — every comment event (save/seen/reject/accept) creates a
  parquet snapshot in `data_storage/versions/` for full audit trail
