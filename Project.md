# MIGR8 AI Backend — Validation API

> Living document for the FastAPI service in this package. Update when routes, models, services, or env config change.

---

## Overview

| Field | Value |
| --- | --- |
| Project name | MIGR8 AI — Validation API |
| Path | `IntelliSAP_MIGR8_Backend/` |
| Purpose | Auth, validation, field mapping, comparison, project reports, and grounded chat for the MIGR8 AI frontend |
| Status | Hackathon demo-ready |
| Default port | `8000` |
| OpenAPI | `http://localhost:8000/docs` |

---

## Tech Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Framework | **FastAPI** `0.115` | Uvicorn with `--reload` for local dev |
| ORM | **SQLAlchemy** `2.0` | Declarative models in `db/models.py` |
| DB | **PostgreSQL** | Via `psycopg2-binary`; URL from `.env` |
| Auth | **JWT** (`python-jose`) + **bcrypt** | Bearer token; no server-side session store |
| Files | **boto3** → S3, or **local disk** | `STORAGE_BACKEND=auto\|local\|s3` |
| Excel read | **openpyxl** (read-only), **polars** + **fastexcel** (calamine) | Via `services/file_stream.py` |
| Excel write | **XlsxWriter** `constant_memory` | Streaming annotated reports (validation + comparison) |
| AI / rules | **AWS Bedrock** Claude Sonnet 5 | Regex, mapping rank, rule suggester, chat |
| Embeddings | **Cohere Embed v4** on Bedrock | TF-IDF fallback when Bedrock unavailable |
| Bedrock HTTP | **httpx** | When `BEDROCK_ACCESS_KEY` is set (bearer REST) |
| Config | **pydantic-settings** | Loads `.env`; `extra="ignore"` |
| Schemas | **Pydantic v2** | Package under `schemas/` |
| Tests | **pytest** `8.3` | Needs live Postgres + `.env` |
| Python | **3.12+** | `psycopg2-binary>=2.9.11` on Windows |

---

## Project Structure

```
IntelliSAP_MIGR8_Backend/
├── main.py                     # FastAPI app, CORS, startup/shutdown, /health, local file serve
├── config.py                   # Settings from .env (bedrock_region, cors_origins, etc.)
├── auth.py                     # bcrypt hash/verify, JWT, get_current_user
├── schema.sql                  # Canonical Postgres DDL (preferred over auto-create)
├── requirements.txt
├── .env.example
├── Project.md
├── data/
│   └── sap_ddic_catalog.json   # SAP DDIC metadata for rule suggestions (~34k lines)
├── migrations/
│   ├── 001_validation_run_names.sql
│   ├── 002_field_mapping_key_and_number_range.sql
│   ├── 003_comparison_runs.sql
│   ├── 003_run_progress.sql
│   └── 004_validation_rule_templates.sql
├── scripts/                    # apply_* migrations, AWS/Bedrock smoke tests, DDIC tooling
├── tests/                      # 11 pytest modules (see Tests section)
├── db/
│   ├── database.py             # engine, SessionLocal, get_db
│   └── models.py               # SQLAlchemy models
├── schemas/
│   ├── auth.py, projects.py, validation.py, mapping.py
│   ├── comparison.py, reports.py, chat.py
│   └── __init__.py
├── routers/
│   ├── auth.py                 # /api/auth/*
│   ├── projects.py             # /api/projects/*
│   ├── validation.py           # /api/runs/*
│   ├── mapping.py              # /api/mappings/*
│   ├── comparison.py           # /api/comparisons/*
│   └── chat.py                 # /api/chat
└── services/
    ├── aws_client.py           # boto3 S3 (AWS_REGION) + Bedrock (BEDROCK_REGION)
    ├── bedrock_llm.py          # Converse wrapper (boto3 or REST bearer)
    ├── s3_service.py           # upload/download/presigned URLs; local fallback
    ├── file_stream.py          # Stream CSV/XLSX headers and rows
    ├── excel_service.py        # Streaming validation → annotated XLSX + stats
    ├── rules_engine.py         # Per-cell validation rules
    ├── regex_generator.py      # Bedrock plain-English → regex
    ├── rule_templates.py       # Curated SAP rule catalog loader/seeder
    ├── rule_suggester.py       # Heuristics + embedding + LLM rule suggestions
    ├── sap_ddic.py             # DDIC catalog helpers for rule suggestions
    ├── job_queue.py            # In-process ProcessPoolExecutor for long jobs
    ├── mapping_pipeline.py     # Background mapping: embed → top-3 → LLM rank
    ├── file_parser.py          # Source/target field-list parsing (mapping)
    ├── embedding_service.py    # Cohere Embed v4 or local TF-IDF
    ├── mapping_engine.py       # Cosine top-3 + datatype scores
    ├── llm_mapping.py          # Bedrock re-rank with confidence + reasoning
    ├── datatype_matcher.py     # SAP datatype compatibility matrix
    ├── comparison_file_service.py  # Streaming xlsx read/write for comparison
    ├── comparison_engine.py    # Composite-key join, equivalence, top-50 discrepancies
    └── chat_service.py         # Grounded Q&A from packed JSON context
```

---

## Environment

Copy `.env.example` → `.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | PostgreSQL connection string |
| `JWT_SECRET` | yes | JWT signing key |
| `JWT_ALGORITHM` | no | Default `HS256` |
| `JWT_EXPIRE_MINUTES` | no | Default `1440` (24h) |
| `STORAGE_BACKEND` | no | `auto` (default) \| `local` \| `s3` |
| `PUBLIC_API_BASE_URL` | no | Default `http://localhost:8000` — local download URLs |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | optional | S3; omit on EC2 for instance role |
| `AWS_REGION` | no | **S3 / RDS region** (e.g. `ap-southeast-2`) |
| `S3_BUCKET` | no | Default `migr8-ai-validation` |
| `BEDROCK_MODEL_ID` | no | Default `us.anthropic.claude-sonnet-5` |
| `BEDROCK_EMBED_MODEL_ID` | no | Default `cohere.embed-v4:0` |
| `EMBEDDING_BACKEND` | no | `auto` \| `bedrock` \| `local` |
| `BEDROCK_REGION` | no | Default `us-east-1` — **Bedrock endpoint** (separate from `AWS_REGION`) |
| `BEDROCK_ACCESS_KEY` | optional | `ABSK…` bearer key for Bedrock REST |
| `CORS_ORIGINS` | no | Comma-separated frontend origins |

**Important:** `AWS_REGION` and `BEDROCK_REGION` are intentionally separate. S3/RDS can live in `ap-southeast-2` while US inference profiles must be called via `us-east-1`.

---

## Data Model

```
users 1──* validation_projects 1──* validation_runs
                                      ├──* validation_fields
                                      └──* validation_exceptions
                                 1──* mappings
                                 |    ├──* mapping_temp
                                 |    └──* final_mapping
                                 └──* comparison_runs
                                      └──* comparison_discrepancies
```

| Table | Role |
| --- | --- |
| `users` | Register / login; JWT `sub` = user id |
| `validation_projects` | Scopes runs per user |
| `validation_runs` | Upload → rules → execute; stats, S3 keys, progress columns |
| `validation_fields` | Per-column rule config; `rule_source` (`user` \| `ai` \| `default`) |
| `validation_rule_templates` | Curated SAP rule catalog for AI suggestions |
| `validation_exceptions` | **Capped** failure samples for results UI (~20 total) |
| `mappings` | Field-mapping run; `number_range_type`, status lifecycle |
| `mapping_temp` | Top-3 candidates JSONB per source field; `key_field` |
| `final_mapping` | User-confirmed mappings; `key` = comparison business key part |
| `comparison_runs` | Preload/postload comparison run |
| `comparison_discrepancies` | Up to 50 worst discrepancies per run |

**Status values:**

- Validation: `draft` → `rules_configured` → `running` → `completed` \| `failed`
- Mapping: `processing` → `awaiting_approval` → `completed` \| `failed`
- Comparison: `draft` → `running` → `completed` \| `failed`

**Full per-row validation detail** is in the annotated Excel on S3 (`result_s3_key`), not in a separate row-results table. The UI downloads that workbook for all rows + `Validation_Failure_Reason`.

**S3 keys:**

- Validation: `validations/{run_id}/source/{filename}`, `validations/{run_id}/result/{stem}.xlsx`
- Mapping: `mappings/{id}/source/…`, `mappings/{id}/target/…`
- Comparison: `comparisons/{run_id}/preload/…`, `postload/…`, `result/comparison_{filename}`

**Migrations (existing DBs):** apply in order `001` → `002` → `003_comparison_runs` → `003_run_progress` → `004_validation_rule_templates`, or use matching `scripts/apply_*` helpers. Fresh installs: `psql "$DATABASE_URL" -f schema.sql`.

---

## API Map

All protected routes use Bearer JWT via `get_current_user`.

### Root (`main.py`)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/health` | no | `status`, `storage`, `llm`, `model`, `embed_model`, `embedding_backend`, `bedrock_region` |
| GET | `/api/local-files/{key:path}` | no | Serves `local_storage/` when `storage=local` |

### Auth — `/api/auth`

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/register` | `{ fullName, email, password }` → `{ token, user }` |
| POST | `/login` | `{ email, password }` → `{ token, user }` |
| GET | `/me` | Current user |
| POST | `/logout` | Stateless ack |

### Projects — `/api/projects`

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/` | Create project `{ name }` |
| GET | `/` | List current user's projects |
| GET | `/{project_id}/report` | Aggregated KPIs (`ProjectReportOut`) |
| GET | `/{project_id}/runs` | Validation runs for project cards |

### Validation — `/api/runs`

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Cross-project list; optional `project_id`, `limit`, `offset` |
| POST | `/?project_id=` | Body `{ name }` → `{ run_id }`; duplicate → **409** |
| GET | `/{run_id}` | Draft UI: name, status, fields, progress, file flags |
| POST | `/{run_id}/upload` | Multipart `file` (.csv or .xlsx); returns `{ fields }` |
| PUT | `/{run_id}/rules` | `FieldRuleIn[]`; Bedrock regex when `regex_prompt` set |
| POST | `/suggest-rules` | AI/heuristic rule suggestions (read-only) |
| POST | `/generate-regex` | `{ field_name, prompt }` → `{ regex }`; failure → **422** |
| POST | `/{run_id}/execute` | **202** — queues background validation job |
| GET | `/{run_id}/result` | Results payload + capped `exceptions` + progress fields |
| GET | `/{run_id}/download-url` | Presigned/local URL for full annotated XLSX |

### Field mapping — `/api/mappings`

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | List runs; optional `project_id`, `limit`, `offset` |
| GET | `/stats` | Dashboard counts: `approved`, `awaitingApproval`, `processing`, `failed`, `total` |
| POST | `/?project_id=` | Multipart source + target + Form `number_range_type`; **202** async pipeline |
| GET | `/{run_id}/result` | Full mapping JSON with prospects + `confirmedTargetField` |
| PATCH | `/{run_id}` | Rename run |
| GET | `/{run_id}/target-fields` | Full SAP target catalog for manual picks |
| GET | `/{run_id}/confirmed` | Confirmed `final_mapping` rows |
| POST | `/{run_id}/confirm` | Upsert confirmations; target must be in catalog or candidates |

### Comparison — `/api/comparisons`

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Cross-project list; optional `project_id`, `limit`, `offset` |
| POST | `/?project_id=` | Body `{ name }` → `{ run_id }`; duplicate → **409** |
| POST | `/{run_id}/upload` | Multipart `preload_file` + `postload_file` (.xlsx only) |
| GET | `/{run_id}/available-mappings` | Completed mappings with confirmed fields |
| POST | `/{run_id}/execute` | Body `ExecuteComparisonRequest`; **202** async job |
| GET | `/{run_id}/result` | Review payload (camelCase) |
| GET | `/{run_id}/download-url` | Annotated preload report URL |

### Chat — `/api/chat`

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/` | Grounded Q&A from packed owned-project JSON; off-topic refused |

---

## Background Jobs (`services/job_queue.py`)

Started on app startup; stopped on shutdown. Uses `ProcessPoolExecutor(max_workers=1)` in production (`ThreadPoolExecutor` under pytest).

| Submit | Job | Trigger |
| --- | --- | --- |
| `submit_validation(run_id)` | Stream-validate source → upload annotated XLSX → persist stats + exceptions | `POST /api/runs/{id}/execute` |
| `submit_mapping(run_id)` | `mapping_pipeline.run_mapping_job` | `POST /api/mappings/` |
| `submit_comparison(run_id)` | `comparison_engine.run_comparison` | `POST /api/comparisons/{id}/execute` |

On startup: marks stale `running` validation/comparison runs and `processing` mappings as `failed`. Ensures progress columns on `validation_runs` exist.

---

## Feature Flows

### Validation

1. Create run with unique name per project.
2. Upload CSV or XLSX; headers seed `validation_fields`.
3. Configure rules (`PUT /rules`) or get suggestions (`POST /suggest-rules` — does not write DB).
4. Execute returns **202**; worker streams rows via `file_stream` + `rules_engine`, writes annotated XLSX with red failing cells and `Validation_Failure_Reason` column.
5. Composite key uniqueness when ≥2 `flag_key` fields.
6. Exception sampling: max **5 per error type**, **20 total** → `validation_exceptions`.
7. Poll `GET /result` for progress (`processedRows`, `totalRows`); download full report via `download-url`.

### Field mapping

1. `POST /mappings/` with `number_range_type` (`internal` \| `external`), source + target files → **202**.
2. Pipeline: parse → embed → top-3 → LLM re-rank → `mapping_temp`; status → `awaiting_approval`.
3. Internal number range + key field: skip AI — full target catalog as manual prospects.
4. User confirms via `POST /confirm`; status → `completed`.

### Comparison

1. Create run, upload paired `.xlsx` files (max 200k rows each).
2. Optional mapping for column/key resolution.
3. Execute returns **202**; worker joins on composite business key, compares values with equivalence rules, stores top 50 discrepancies, streams annotated preload report.
4. `values_equivalent` ignores zero-padding, decimal noise, sign formats, date format differences on keys and values.

### Chat

`chat_service` packs owned project/run/mapping JSON (no SQL from model). Comparison data is marked unavailable in context. Bedrock answers from the pack only; off-topic prompts refused in code.

---

## Services (key behavior)

| Service | Responsibility |
| --- | --- |
| `rules_engine.validate_cell` | Types, regex `fullmatch`, keys, dates, email, mobile, case rules |
| `excel_service` | Streaming validation → XLSX; `Validation_Failure_Reason` column |
| `regex_generator` | Bedrock → JSON regex; strips `^`/`$` |
| `bedrock_llm` | API key (httpx) or IAM (boto3); parses Sonnet 5 `reasoningContent` + `text` blocks |
| `rule_suggester` | Heuristics → DDIC/template embedding match → optional LLM batch; never sets `flag_key` |
| `comparison_engine` | Composite-key join, `FORMAT_CHANGE` vs `VALUE_MISMATCH`, bounded heap for discrepancies |
| `s3_service` | `auto` uses local disk when AWS creds are placeholders |

---

## Tests

```bash
pytest tests/ -q    # needs Postgres + .env
```

| File | Focus |
| --- | --- |
| `test_suggest_rules.py` | Rule suggester + endpoint |
| `test_large_file.py` | CSV streaming validation |
| `test_composite_keys.py` | Composite/single key uniqueness, exception caps |
| `test_project_report.py` | `GET /api/projects/{id}/report` |
| `test_comparison.py` | Full comparison API |
| `test_comparison_equivalence.py` | `values_equivalent`, `canonical_key_part` |
| `test_chat.py` | Prefilter, context pack, mocked Bedrock |
| `test_embedding_service.py` | Local embed + mocked Cohere |
| `test_bedrock_llm.py` | Mocked regex + rank_candidates |
| `test_run_names.py` | Run naming uniqueness |

---

## Local Run

```bash
cd IntelliSAP_MIGR8_Backend
python -m venv venv
.\venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env

# Fresh DB:
# psql "%DATABASE_URL%" -f schema.sql

# Existing DB — apply migrations in order (see Migrations section)

uvicorn main:app --reload --port 8000 --reload-exclude "venv"
```

Smoke checks:

```bash
curl http://localhost:8000/health
python scripts/test_regex_bedrock.py
```

**Tip:** Use `--reload-exclude "venv"` so `pip install` while the server is running does not trigger reload storms on Windows.

---

## Decisions & Conventions

1. Bearer JWT — no server-side session store.
2. Async execute for validation, mapping, and comparison — **202** + poll result endpoints.
3. `schema.sql` is source of truth; `create_all` only when `users` table missing.
4. `AWS_REGION` ≠ `BEDROCK_REGION`.
5. Composite keys — ≥2 `flag_key` fields → tuple uniqueness.
6. Exception cap in DB — diverse samples for UI; full detail in Excel download.
7. Mapping confirmation is per-field upsert on `(mapping_id, source_field)`.
8. Comparison is xlsx in/out; 200k row cap; streaming reads/writes.
9. Keep routers thin; business logic in `services/`.
10. Always `str(uuid)` in API responses when schema field is `str`.

---

## Open Questions / TBD

- Celery/RQ if multiple uvicorn workers need isolated job execution
- Password reset
- `validation_row_results` table if UI needs paginated full-row API without Excel download
- Un-confirm / delete single `final_mapping` row endpoint
- Live SAP table fetch for mapping target fields (upload-only today)
- `schema.sql` CHECK for `mappings.status` should include `awaiting_approval`

---

## Session Log

### 2026-08-14 — Project.md refresh

- Synced docs with current codebase: async jobs for all three pillars, `job_queue`, `mapping_pipeline`, `rule_suggester`, `file_stream` streaming validation, migrations 003_run_progress + 004_validation_rule_templates, mapping `awaiting_approval` + `/stats` + `PATCH` + `/target-fields`.

### 2026-08-14 — Large-file validation

- `POST /api/runs/{id}/execute` returns **202**; worker streams CSV/XLSX and writes annotated XLSX.
- Progress columns: `processed_rows`, `total_rows`, `error_message`.

### 2026-08-14 — Comparison value equivalence

- `values_equivalent` + `canonical_key_part` for zero-padding, decimals, signs, dates.
- Tests in `test_comparison.py`, `test_comparison_equivalence.py`.

### 2026-08-13 — Results chatbot, comparison, field mapping

- `POST /api/chat/` grounded assistant.
- Comparison module: `comparison_runs`, `comparison_discrepancies`, async execute.
- Field mapping: `number_range_type`, `key_field`, `final_mapping.key`, `awaiting_approval`.

### 2026-08-13 — Bedrock region + Sonnet 5

- `BEDROCK_REGION` separate from `AWS_REGION`; `BEDROCK_ACCESS_KEY` REST path.
- Sonnet 5: no `temperature`; parse `reasoningContent` + `text` blocks.

---

## Change Checklist

When you change the backend, update this file if you touch:

- [ ] New dependency in `requirements.txt`
- [ ] New route or response shape
- [ ] Model / `schema.sql` change (+ migration if needed)
- [ ] New env var / `.env.example`
- [ ] Service behavior (rules, Excel, S3, Bedrock, jobs)
- [ ] Test file added or renamed
