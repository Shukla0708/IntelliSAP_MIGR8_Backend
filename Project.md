# MIGR8 AI Backend — Validation API

> Living document for the FastAPI service in this package. Update when routes, models, services, or env config change.

---

## Overview

| Field | Value |
| --- | --- |
| Project name | MIGR8 AI — Validation API |
| Path | `IntelliSAP_MIGR8_Backend/` |
| Purpose | Auth, validation runs, field mapping, and project reports for the MIGR8 AI frontend |
| Status | Hackathon demo-ready |
| Default port | `8000` |
| OpenAPI | `http://localhost:8000/docs` |

---

## Tech Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Framework | **FastAPI** `0.115` | Uvicorn with `--reload` for local dev |
| ORM | **SQLAlchemy** `2.0` | Declarative models in `db/models.py` |
| DB | **PostgreSQL** | Via `psycopg2-binary`; URL from `.env` (RDS in deploy) |
| Auth | **JWT** (`python-jose`) + **bcrypt** (direct; not passlib) | Bearer token |
| Files | **boto3** → S3, or **local disk** | `STORAGE_BACKEND=auto\|local\|s3` |
| Excel | **openpyxl** | Headers, red-fill failures, reason column |
| AI rules / mapping | **AWS Bedrock** Claude Sonnet 5 | Plain English → regex; field-mapping re-rank |
| Bedrock HTTP | **httpx** | Used when `BEDROCK_ACCESS_KEY` is set (bearer REST) |
| Embeddings (mapping) | **numpy** + local TF-IDF | No model download; swappable later |
| Config | **pydantic-settings** | Loads `.env`; `extra="ignore"` for legacy vars |
| Schemas | **Pydantic v2** | Package under `schemas/` |
| Python | **3.12+ / 3.13** | Needs `psycopg2-binary>=2.9.11` on Windows |

---

## Project Structure

```
IntelliSAP_MIGR8_Backend/
├── main.py                 # FastAPI app, CORS, startup create_all, /health, local file serve
├── config.py               # Settings from .env (incl. bedrock_region, cors_origins)
├── auth.py                 # hash/verify password, JWT, get_current_user
├── schema.sql              # Canonical Postgres DDL (preferred over auto-create)
├── migrations/
│   └── 001_validation_run_names.sql
├── requirements.txt
├── .env.example
├── Project.md              # This file
├── scripts/
│   ├── check_aws_access.py      # S3 + Bedrock smoke checks
│   ├── probe_bedrock_profiles.py  # Try inference profile IDs
│   ├── test_invoke_model.py       # Minimal Bedrock converse call
│   ├── test_regex_bedrock.py      # End-to-end regex_generator test
│   └── apply_run_name_migration.py
├── tests/
│   ├── test_bedrock_llm.py        # Mocked Bedrock regex + mapping tests
│   ├── test_composite_keys.py     # Composite / single-key uniqueness
│   ├── test_run_names.py          # Run name uniqueness + list/detail
│   └── test_project_report.py     # GET /api/projects/{id}/report
├── db/
│   ├── database.py         # engine, SessionLocal, get_db
│   └── models.py           # User, ValidationProject, ValidationRun, Field, Exception, Mapping, …
├── schemas/
│   ├── __init__.py         # Re-exports for `from schemas import ...`
│   ├── auth.py
│   ├── projects.py
│   ├── validation.py
│   ├── reports.py
│   └── mapping.py
├── routers/
│   ├── auth.py             # /api/auth/*
│   ├── projects.py         # /api/projects/*
│   ├── validation.py       # /api/runs/*
│   └── mapping.py          # /api/mappings/*
└── services/
    ├── aws_client.py        # boto3 clients (S3 uses AWS_REGION; Bedrock uses BEDROCK_REGION)
    ├── bedrock_llm.py       # Bedrock Converse wrapper (boto3 or REST bearer)
    ├── s3_service.py
    ├── excel_service.py
    ├── rules_engine.py
    ├── regex_generator.py
    ├── file_parser.py       # source/target field-list CSV+XLSX parsing (mapping)
    ├── embedding_service.py # Cohere Embed v4 on Bedrock (TF-IDF fallback)
    ├── mapping_engine.py    # cosine top-3 candidates + datatype match score (mapping)
    ├── llm_mapping.py       # Bedrock re-rank + reasoning (mapping)
    └── datatype_matcher.py  # SAP-type compatibility matrix (mapping)
```

---

## Environment

Copy `.env.example` → `.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | e.g. `postgresql://user:pass@host:5432/migr8` |
| `JWT_SECRET` | yes | Signing key for access tokens |
| `JWT_ALGORITHM` | no | Default `HS256` |
| `JWT_EXPIRE_MINUTES` | no | Default `1440` (24h) |
| `AWS_ACCESS_KEY_ID` | optional | IAM keys for S3; omit on EC2 to use instance role |
| `AWS_SECRET_ACCESS_KEY` | optional | Same |
| `AWS_REGION` | no | Default `ap-south-1` in code — **S3 / RDS region** (e.g. `ap-southeast-2`) |
| `S3_BUCKET` | no | Default `migr8-ai-validation` |
| `STORAGE_BACKEND` | no | `auto` (default) \| `local` \| `s3` — use `s3` on EC2 |
| `PUBLIC_API_BASE_URL` | no | Default `http://localhost:8000` — used for local download URLs |
| `BEDROCK_MODEL_ID` | no | Default `us.anthropic.claude-sonnet-5` — regex + mapping LLM |
| `BEDROCK_EMBED_MODEL_ID` | no | Default `cohere.embed-v4:0` — field-mapping embeddings |
| `EMBEDDING_BACKEND` | no | `auto` (Cohere if Bedrock creds) \| `bedrock` \| `local` |
| `CORS_ORIGINS` | no | Comma-separated frontend origins (add EC2 URL on deploy) |

**Important:** `AWS_REGION` and `BEDROCK_REGION` are intentionally separate. S3/RDS can live in `ap-southeast-2` while Bedrock inference profiles like `us.anthropic.claude-sonnet-5` must be called via `us-east-1`.

`config.py` uses `extra="ignore"` so legacy keys (e.g. `GROQ_API_KEY`) in `.env` do not crash startup.

CORS origins are read from `CORS_ORIGINS`. Default includes common localhost ports. On EC2, add your frontend URL.

---

## Data model

```
users 1──* validation_projects 1──* validation_runs
                                      ├──* validation_fields
                                      └──* validation_exceptions
                                 1──* mappings
                                      ├──* mapping_temp
                                      └──* final_mapping
```

| Table | Role |
| --- | --- |
| `users` | Register / login; JWT `sub` = user id |
| `validation_projects` | Scopes runs per user |
| `validation_runs` | One upload → configure → execute cycle + aggregate stats; **`name` VARCHAR(120) NOT NULL**, unique per `(project_id, name)` |
| `validation_fields` | Per-column rule flags/config for a run |
| `validation_exceptions` | Capped failure samples for results UI |
| `mappings` | Source+target upload → embed → LLM-rank cycle |
| `mapping_temp` | Top-3 SAP candidates per source field (JSONB) |
| `final_mapping` | User-confirmed mappings; `(mapping_id, source_field)` unique |

**Run status:** `draft` → `rules_configured` → `running` → `completed` \| `failed`

**Mapping status:** `processing` → `completed` \| `failed`

**Run names:** User-provided at create (trimmed, non-empty, ≤120 chars). Duplicate within project → HTTP 409.

**S3 keys:**

- Source: `validations/{run_id}/source/{filename}`
- Result: `validations/{run_id}/result/{filename}`

Prefer applying `schema.sql` in pgAdmin/`psql`. On startup, `Base.metadata.create_all` also creates missing tables (hackathon shortcut).

```bash
psql "$DATABASE_URL" -f migrations/001_validation_run_names.sql   # existing DBs with run_name
```

---

## API map

### Health & local files

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/health` | no | `{ status, storage, llm, model, bedrock_region }` |
| GET | `/api/local-files/{key:path}` | no | Serves files from `local_storage/` when `storage=local` |

### Auth — `/api/auth`

| Method | Path | Auth | Body / notes | Response |
| --- | --- | --- | --- | --- |
| POST | `/register` | no | `fullName`, `email`, `password` | `{ token, user }` |
| POST | `/login` | no | `email`, `password` | `{ token, user }` |
| GET | `/me` | Bearer | — | `UserOut` |
| POST | `/logout` | Bearer | Stateless JWT ack | `{ message, userId }` |

### Projects — `/api/projects`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/` | Bearer | `{ name }` → `ProjectOut` |
| GET | `/` | Bearer | List current user's projects |
| GET | `/{project_id}/runs` | Bearer | Runs list for project cards |
| GET | `/{project_id}/report` | Bearer | Aggregated validation KPIs (`ProjectReportOut`) |

### Field mapping — `/api/mappings`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/?project_id=` | Bearer | Multipart `source_file` + `target_file` → pipeline → `mapping_temp` |
| GET | `/{run_id}/result` | Bearer | Re-fetch mapping result JSON |
| POST | `/{run_id}/confirm` | Bearer | Body `{ fields: [{ sourceField, targetField }] }` → upsert `final_mapping` |

**Source file** columns: Field Name, Description, Key Field flag, Datatype. **Target file**: SAP Table, SAP Field, Description, Table Description, Datatype (aliases in `file_parser.py`).

Ownership: every run/project access checks the JWT user owns the project.

### Validation runs — `/api/runs`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/` | Bearer | Cross-project list; optional `project_id`, `limit`, `offset` |
| POST | `/?project_id=` | Bearer | Body `{ name }` → `{ run_id }`; duplicate → **409** |
| GET | `/{run_id}` | Bearer | Draft edit UI: `name`, `status`, `fields[]`, `has_source_file` |
| POST | `/{run_id}/upload` | Bearer | Multipart `file`; stores S3/local; returns `{ fields }` |
| PUT | `/{run_id}/rules` | Bearer | `FieldRuleIn[]` → persists flags/config; re-generates regex from `regex_prompt` when set |
| POST | `/generate-regex` | Bearer | `{ field_name, prompt }` → `{ regex }`; failure → **422** `{ message, reason }` |
| POST | `/{run_id}/execute` | Bearer | Sync validation; updates stats + exceptions |
| GET | `/{run_id}/result` | Bearer | Payload for results page |
| GET | `/{run_id}/download-url` | Bearer | `{ url }` presigned GET (or local URL) |

---

## Services (behavior)

### `rules_engine.validate_cell`

Per-cell checks driven by field config:

- Mandatory / literal null-N/A
- Data types: int, decimal, boolean, string/char
- Max length, decimal precision
- Case: uppercase / lowercase / camelCase
- Email, mobile, date formats, special chars
- Custom regex via **`re.fullmatch`**
- Single-column key uniqueness (`seen_keys` set per field)

**Key normalization:** `normalize_key()` treats Excel `1` and `1.0` as the same key.

**Dates (Excel-aware):** Accepts `datetime`/`date` objects from openpyxl plus string formats (`%Y-%m-%d`, `%d-%m-%Y`, `%m/%d/%Y`, `%d/%m/%Y`, `%Y%m%d`, `%d%m%y`, etc.). Date separators are not flagged as special chars when the value is a valid date.

### `excel_service.run_validation`

- **`extract_headers`** — row 1 → column names for the rules UI
- **`run_validation`** — annotate workbook (red fill, `Validation_Failure_Reason` column), return stats + exceptions

**Composite keys:** When **two or more** fields have `flag_key`, uniqueness is enforced on the **combined** tuple (e.g. `CustomerID + OrderID`), not per column. Duplicate pairs flag all key columns with `Duplicate composite key value (same as row N)`.

**Exception sampling:** At most **5 rows per error type** and **20 total** stored (`MAX_EXCEPTIONS_PER_TYPE`, `MAX_STORED_EXCEPTIONS`) so one noisy error does not hide others.

### `regex_generator`

Bedrock Claude Sonnet 5 via `bedrock_llm.chat()` → JSON `{"regex":"..."}`. Strips `^`/`$` (engine uses `fullmatch`). On **`PUT /{run_id}/rules`**, if `regex_prompt` is set, Bedrock regenerates `regex` (Rule 5 stays LLM-driven even if UI Generate was skipped). Falls back to client-supplied `regex` on failure.

### `bedrock_llm`

- **Auth path A:** `BEDROCK_ACCESS_KEY` set → REST `POST …/converse` with `Authorization: Bearer …` (httpx)
- **Auth path B:** No API key → boto3 `bedrock-runtime` client (IAM keys or instance role)
- Uses **`BEDROCK_REGION`** for the endpoint (not `AWS_REGION`)
- **Claude Sonnet 5 quirks:** no `temperature` in `inferenceConfig`; responses may include `reasoningContent` blocks before the text — parser collects all `text` blocks
- `strip_markdown_fences()` for JSON cleanup

### `aws_client`

- S3 client → `AWS_REGION` + optional IAM keys; `certifi` for SSL on Windows
- Bedrock client → `BEDROCK_REGION`; sets `AWS_BEARER_TOKEN_BEDROCK` when API key is configured
- Placeholder keys (`your-key`, `changeme`, etc.) treated as unset

### `s3_service`

`upload_bytes` / `download_bytes` / `presigned_url` / `storage_mode()`. `STORAGE_BACKEND=auto` uses local disk under `local_storage/` when AWS keys are placeholders.

### Mapping services

`parse_source_fields` / `parse_target_fields` — read `.csv` or `.xlsx`, match fixed headers case-insensitively (with a small alias list per column), return one dict per row. Raises `ValueError` (→ HTTP 422) if a required column isn't found or the file has no data rows. Source rows: `field_name`, `description`, `key_field` (bool, normalized from `Y/N`/`X`/`TRUE/FALSE`/`1/0`/`yes/no`), `datatype`. Target rows: `sap_table`, `sap_field`, `description`, `table_description`, `datatype`.

### `embedding_service` (mapping)

`embed_texts(list[str]) -> np.ndarray` — **Cohere Embed v4** on Bedrock (`BEDROCK_EMBED_MODEL_ID`, default `cohere.embed-v4:0`) via InvokeModel, same creds as Claude (`BEDROCK_ACCESS_KEY` or IAM). Batches of 96. L2-normalized rows. Falls back to local TF-IDF when `EMBEDDING_BACKEND=local` or no Bedrock credentials.

### `mapping_engine` (mapping)

`top_candidates` — embeds `"{field}: {description}"` for source rows and `"{table}.{field}: {description}"` for target rows, cosine-similarity matrix, returns the top 3 target candidates per source field with a raw `embedding_score` (-1..1) and a `datatype_match_score` (0-100, or `None` if either side's datatype is missing) from `datatype_matcher`.

### `llm_mapping` (mapping)

`rank_candidates` — sends one source field + its top-3 embedding candidates (including target table description, for context) to **Bedrock** (`BEDROCK_MODEL_ID`, default Claude Sonnet 5), gets back the same candidates re-ordered with a `confidence_score` (0-100) and a ~20-30 word `reasoning` each; `datatype_match_score` passes through untouched (not sent to the LLM). JSON-only response. On LLM failure/invalid JSON, the router falls back to embedding-only scoring (`confidence_score = embedding_score * 100`) rather than failing the whole run.

### `datatype_matcher` (mapping)

`datatype_match_score(source_datatype, target_datatype) -> float | None` — hardcoded SAP-type compatibility groups (e.g. `CHAR`/`STRING`/`TEXT`, `NUMC`/`INT`/`NUMBER`, `DATS`/`DATE`, `CURR`/`DEC`/`FLOAT`, `FLAG`/`BOOLEAN`). Exact match after normalization → 100, same group → 60, otherwise → 0. Returns `None` if either datatype is missing.

---

## Pydantic schemas (`schemas/`)

| Module | Models |
| --- | --- |
| `auth.py` | `RegisterRequest`, `LoginRequest`, `UserOut`, `AuthResponse` |
| `projects.py` | `ProjectCreate`, `ProjectOut` — `id` serialized as `str` |
| `reports.py` | `ProjectReportOut`, `ReportValidationSection`, `ReportReadiness`, … |
| `validation.py` | `CreateRunRequest`, `FieldRuleIn`, `RegexGenerateRequest/Response`, `RunDetailOut`, `RunFieldOut` |
| `mapping.py` | `ConfirmedFieldIn`, `ConfirmMappingRequest` |

Routers import via `from schemas import ...`.

---

## Local run

```bash
cd IntelliSAP_MIGR8_Backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # fill values

uvicorn main:app --reload --port 8000
```

Smoke checks:

```bash
curl http://localhost:8000/health
# {"status":"ok","storage":"local|s3","llm":"bedrock","model":"us.anthropic.claude-sonnet-5","bedrock_region":"us-east-1"}

python scripts/test_regex_bedrock.py   # needs BEDROCK_ACCESS_KEY or IAM Bedrock access
```

Tests (needs Postgres + `.env`):

```bash
pytest tests/ -q
```

---

## Decisions & Conventions

1. **Bearer JWT** in `Authorization` header — no server-side session store.
2. **CamelCase in auth JSON** (`fullName`); field rules use snake_case on the wire.
3. **Sync execute** for demo-sized files; large files should move to a background job.
4. **`schema.sql` is source of truth** for constraints; SQLAlchemy `create_all` is a hackathon shortcut.
5. **Never log secrets** from `.env`.
6. Keep routers thin; business logic in `services/`.
7. **bcrypt directly** — avoid passlib + bcrypt 5.x issues on Windows.
8. **Always `str(uuid)` in API responses** when schema field is `str`.
9. **`AWS_REGION` ≠ `BEDROCK_REGION`** — S3/RDS region vs Bedrock inference profile endpoint.
10. **Rule 5 is LLM-only** — Bedrock generates every custom regex from plain English.
11. **Composite keys** — ≥2 `flag_key` fields → tuple uniqueness, not per-column.
12. **Exception cap** — diverse error types in UI despite many failures in the file.
13. **Bedrock API key vs IAM** — API key uses httpx REST; IAM uses boto3. S3 always uses IAM keys/role.
14. **Mapping confirmation is per-field** — upsert on `(mapping_id, source_field)`.

---

## Open Questions / TBD

- Background job for `execute` (Celery / RQ / BackgroundTasks)
- Password reset
- Stricter alignment of auto-created tables with `schema.sql` CHECKs
- Remove unused `groq` / `passlib` from `requirements.txt` once venv is rebuilt
- Field mapping: batch multiple source fields per LLM call for large files
- Field mapping: list/edit confirmed `final_mapping` rows endpoint
- Drop debug `print` in `rules_engine.validate_cell` before production

---

## Session Log

### 2026-08-13 — Bedrock region + API key + Sonnet 5 response parsing

- Added `BEDROCK_REGION` (default `us-east-1`) separate from `AWS_REGION` for S3/RDS.
- `BEDROCK_ACCESS_KEY` (`ABSK…`) → httpx REST with bearer token; IAM path unchanged via boto3.
- `bedrock_llm`: omit deprecated `temperature`; parse `reasoningContent` + `text` blocks from Sonnet 5.
- `/health` returns `bedrock_region`, `storage`, `llm`, `model`.
- Scripts: `test_regex_bedrock.py`, `probe_bedrock_profiles.py`, `check_aws_access.py`.
- `generate-regex` returns **422** with `{ message, reason }` on failure.

### 2026-08-13 — Composite key validation

- `excel_service`: when ≥2 fields have `flag_key`, enforce composite uniqueness across the row tuple.
- `normalize_key()` matches Excel int/float (`1` vs `1.0`).
- Exception sampling: max 5 per error type, 20 total stored.
- Tests: `tests/test_composite_keys.py`.

### 2026-08-13 — Field mapping feature

- Router `routers/mapping.py`: parse → embed → top-3 → Bedrock re-rank → `mapping_temp` / `final_mapping`.
- Services: `file_parser`, `embedding_service`, `mapping_engine`, `llm_mapping`, `datatype_matcher`.

### 2026-08-13 — Bedrock LLM migration (Groq removed from code)

- `services/bedrock_llm.py` for regex + mapping; default `us.anthropic.claude-sonnet-5`.
- `services/aws_client.py` for IAM-role-aware boto3.
- Tests: `tests/test_bedrock_llm.py` (mocked).

### 2026-08-13 — Project report + cross-project runs + run names

- `GET /api/projects/{project_id}/report` — `schemas/reports.py`, `tests/test_project_report.py`.
- `GET /api/runs/` — cross-project activity list with `project_id` / `project_name`.
- Validation run `name` unique per project; migration `001_validation_run_names.sql`.

### 2026-08-13 — Logout + auth

- `POST /api/auth/logout` — client clears JWT (stateless).

### 2026-08-12 — Windows / Python 3.13 fixes

- `psycopg2-binary` 2.9.11, direct bcrypt, `ProjectOut` UUID → str coercion.
- Schemas split into `schemas/` package.

### 2026-08-13 — Date validation + regex hardening

- Excel `datetime`/`date` cells accepted; `re.fullmatch` for regex rules.
- Repo: https://github.com/Shukla0708/migr8-AI-backend

---

## Change Checklist

When you change the backend, update this file if you touch:

- [ ] New dependency in `requirements.txt`
- [ ] New route or response shape
- [ ] Model / `schema.sql` change (+ migration if needed)
- [ ] New env var / `.env.example`
- [ ] Service behavior (rules, Excel, S3, Bedrock)
- [ ] Test file added or renamed
