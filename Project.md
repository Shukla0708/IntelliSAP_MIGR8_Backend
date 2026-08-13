# MIGR8 AI Backend — Validation API

> Living document for the FastAPI service in this package. Update when routes, models, services, or env config change.

---

## Overview

| Field | Value |
| --- | --- |
| Project name | MIGR8 AI — Validation API |
| Path | `migr8-validation-package/backend/` |
| Purpose | Auth + validation runs for the MIGR8 AI frontend (Excel upload, rule config, execute, results, download) |
| Status | Hackathon demo-ready |
| Default port | `8000` |
| OpenAPI | `http://localhost:8000/docs` |

---

## Tech Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Framework | **FastAPI** `0.115` | Uvicorn |
| ORM | **SQLAlchemy** `2.0` | Declarative models in `db/models.py` |
| DB | **PostgreSQL** | Via `psycopg2-binary`; URL from `.env` |
| Auth | **JWT** (`python-jose`) + **bcrypt** (direct; not passlib) | Bearer token |
| Files | **boto3** → S3, or **local disk** | `STORAGE_BACKEND=auto|local|s3` |
| Excel | **openpyxl** | Headers, red-fill failures, reason column |
| AI rules | **Groq** `llama-3.3-70b-versatile` | Plain English → regex |
| Config | **pydantic-settings** | Loads `.env` |
| Schemas | **Pydantic v2** | Package under `schemas/` |
| Python | **3.13 tested on Windows** | Needs `psycopg2-binary>=2.9.11`, `httpx==0.27.2` (Groq compat) |

---

## Project Structure

```
backend/
├── main.py                 # FastAPI app, CORS, startup create_all, /health
├── config.py               # Settings from .env
├── auth.py                 # hash/verify password, JWT, get_current_user
├── schema.sql              # Canonical Postgres DDL (preferred over auto-create)
├── migrations/             # Incremental SQL (apply after schema exists)
│   └── 001_validation_run_names.sql
├── requirements.txt
├── .env.example
├── Project.md              # This file
├── tests/
│   └── test_run_names.py   # Create-run naming + uniqueness
├── db/
│   ├── database.py         # engine, SessionLocal, get_db
│   └── models.py           # User, ValidationProject, ValidationRun, Field, Exception
├── schemas/
│   ├── __init__.py         # Re-exports for `from schemas import ...`
│   ├── auth.py
│   ├── projects.py
│   └── validation.py
├── routers/
│   ├── auth.py             # /api/auth/*
│   ├── projects.py         # /api/projects/*
│   └── validation.py       # /api/runs/*
└── services/
    ├── s3_service.py
    ├── excel_service.py
    ├── rules_engine.py
    └── regex_generator.py
```

---

## Environment

Copy `.env.example` → `.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | e.g. `postgresql://postgres:pass@localhost:5432/migr8` |
| `JWT_SECRET` | yes | Signing key for access tokens |
| `JWT_ALGORITHM` | no | Default `HS256` |
| `JWT_EXPIRE_MINUTES` | no | Default `1440` (24h) |
| `AWS_ACCESS_KEY_ID` | for S3 | Can stay `your-key` — then storage uses local disk |
| `AWS_SECRET_ACCESS_KEY` | for S3 | Same |
| `AWS_REGION` | no | Default `ap-south-1` |
| `S3_BUCKET` | no | Default `migr8-ai-validation` |
| `STORAGE_BACKEND` | no | `auto` (default) \| `local` \| `s3` |
| `PUBLIC_API_BASE_URL` | no | Default `http://localhost:8000` — used for local download URLs |
| `GROQ_API_KEY` | for Rule 5 | Checkbox rules work without it; generate-regex needs Groq |

CORS allows local frontend origins: `http://localhost:3000`, `http://127.0.0.1:3000`, plus common Vite ports `5173` / `4173` (and `:3001`). `localhost` and `127.0.0.1` are different origins — both are listed. Add any deployed frontend URL to `_CORS_ORIGINS` in `main.py`.

---

## Data model

```
users 1──* validation_projects 1──* validation_runs
                                      ├──* validation_fields
                                      └──* validation_exceptions
```

| Table | Role |
| --- | --- |
| `users` | Register / login; JWT `sub` = user id |
| `validation_projects` | Scopes “previous runs” list; FK for runs |
| `validation_runs` | One upload → configure → execute cycle + aggregate stats; **`name` VARCHAR(120) NOT NULL**, unique per `(project_id, name)` |
| `validation_fields` | Per-column rule flags/config for a run |
| `validation_exceptions` | Capped failure samples (~60) for results UI |

**Run status:** `draft` → `rules_configured` → `running` → `completed` | `failed`

**Run names:** User-provided at create time (trimmed, non-empty, ≤120 chars). No default like `"New validation run"`. Duplicate names within the same project → HTTP 409; the same name is allowed across different projects.

**S3 keys:**

- Source: `validations/{run_id}/source/{filename}`
- Result: `validations/{run_id}/result/{filename}`

Prefer applying `schema.sql` in pgAdmin/`psql`. On startup, `Base.metadata.create_all` also creates missing tables (hackathon shortcut; weaker constraints than SQL). For existing databases that still have `run_name` / the old default, apply:

```bash
psql "$DATABASE_URL" -f migrations/001_validation_run_names.sql
```

That migration renames `run_name` → `name`, backfills duplicate `"New validation run"` rows to unique names, drops the default, and adds `UNIQUE (project_id, name)`.

---

## API map

### Auth — `/api/auth`

| Method | Path | Auth | Body / notes | Response |
| --- | --- | --- | --- | --- |
| POST | `/register` | no | `fullName`, `email`, `password` | `{ token, user }` |
| POST | `/login` | no | `email`, `password` | `{ token, user }` |
| GET | `/me` | Bearer | — | `UserOut` |
| POST | `/logout` | Bearer | Stateless JWT ack; client discards token | `{ message, userId }` |

### Projects — `/api/projects`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/` | Bearer | `{ name }` → `ProjectOut` |
| GET | `/` | Bearer | List current user’s projects |
| GET | `/{project_id}/runs` | Bearer | Runs list shaped for frontend cards (`id`, `name`, `records`, `ranAt`, `status`, `errors`) |

### Validation runs — `/api/runs`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/` | Bearer | Cross-project list for current user; optional `project_id`, `limit`, `offset`; includes `project_id` + `project_name` |
| POST | `/?project_id=` | Bearer | Body `{ name }` (trimmed, required) → `{ run_id }`; duplicate name in project → **409** |
| POST | `/{run_id}/upload` | Bearer | Multipart `file`; stores S3; returns `{ fields }` |
| PUT | `/{run_id}/rules` | Bearer | `FieldRuleIn[]` → persists flags/config |
| POST | `/generate-regex` | Bearer | `{ field_name, prompt }` → `{ regex }` |
| POST | `/{run_id}/execute` | Bearer | Sync validation; updates stats + exceptions |
| GET | `/{run_id}/result` | Bearer | Payload for results page (`runName` = stored name) |
| GET | `/{run_id}/download-url` | Bearer | `{ url }` presigned GET |

Ownership: every run/project access checks the JWT user owns the project. Cross-project `GET /api/runs/` never returns another user’s runs.

---

## Services (behavior)

### `rules_engine.validate_cell`

Per-cell checks driven by field config:

- Mandatory / literal null-N/A
- Data type: int, decimal, boolean, string/char
- Max length, decimal precision
- Case: uppercase / lowercase / camelCase
- Email, mobile, date formats, special chars
- Custom regex via **`re.fullmatch`** (entire cell must match)
- Key uniqueness (in-run `seen_keys` set)

**Dates (Excel-aware):** openpyxl returns real `datetime`/`date` objects for date cells (not `"21-05-2024"` text). Those objects are accepted as valid dates. String values still accept `%Y-%m-%d`, `%d-%m-%Y`, `%m/%d/%Y`, `%d/%m/%Y` (plus datetime string forms). Date separators (`-` / `/`) are not treated as disallowed special characters when the value is a valid date. For regex on date cells, common display forms (`YYYY-MM-DD`, `DD-MM-YYYY`, etc.) are tried so a DD-MM pattern can still pass an Excel date cell.

### `excel_service`

- `extract_headers` — row 1 → column names for the rules table
- `run_validation` — annotate workbook: red fill on failing cells, append `Validation_Failure_Reason`, return stats + up to 60 exceptions

### `regex_generator`

**Always LLM-driven (hackathon Rule 5):** Groq `llama-3.3-70b-versatile` turns plain English → JSON `{"regex":"..."}`. Pattern is compiled before return; stray `^`/`$` anchors are stripped because the engine uses `re.fullmatch`. System prompt includes few-shot examples (e.g. `"starts with H4"` → `H4.*`) so the model rejects values that break the rule.

On **`PUT /{run_id}/rules`**, if `regex_prompt` is set, the backend calls Groq again and stores the resulting `regex` (so Rule 5 stays LLM-backed even if the UI Generate button was skipped). Falls back to any client-supplied `regex` if generation fails.

### `s3_service`

`upload_bytes` / `download_bytes` / `presigned_url` — uses S3 when real AWS keys are set; otherwise **local disk** under `local_storage/` (`STORAGE_BACKEND=auto`).

---

## Pydantic schemas (`schemas/`)

| Module | Models |
| --- | --- |
| `auth.py` | `RegisterRequest`, `LoginRequest`, `UserOut`, `AuthResponse` — email is plain `str` with simple `@` / domain checks (not strict `EmailStr`) |
| `projects.py` | `ProjectCreate`, `ProjectOut` — `id` always serialized as `str` (UUID coerced) |
| `validation.py` | `CreateRunRequest`, `FieldRuleIn`, `RegexGenerateRequest`, `RegexGenerateResponse` |

Routers import via `from schemas import ...` (`schemas/__init__.py` re-exports).

---

## Local run

```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # fill values

# Option A: auto-create tables on startup
uvicorn main:app --reload --port 8000

# Option B: apply schema.sql first, then uvicorn
# psql "$DATABASE_URL" -f schema.sql

# Existing DB with run_name / old defaults:
# psql "$DATABASE_URL" -f migrations/001_validation_run_names.sql
```

Smoke checks:

- `GET /health` → `{"status":"ok"}`
- Swagger: `/docs` → register → login → create project → create run with `{ name }` → upload

Tests (needs Postgres + `.env`):

```bash
pytest tests/test_run_names.py -q
```

---

## Decisions & Conventions

1. **Bearer JWT in Authorization header** — no cookie session yet.
2. **CamelCase in auth JSON** (`fullName`) to match frontend forms; field rules use snake_case on the wire.
3. **Sync execute** for demo size; large files should move to a queue + poll `status`.
4. **`schema.sql` is source of truth** for production-like constraints; SQLAlchemy models power the app + optional auto-create.
5. **Never log secrets** from `.env`; keep `.env` out of git.
6. Keep routers thin; business logic in `services/`.
7. **Hash passwords with `bcrypt` directly** — avoid passlib + bcrypt 5.x wrap-bug crash on Windows/Python 3.13.
8. **Always `str(uuid)` in API response models** — FastAPI response validation rejects raw `UUID` when the schema field is `str` (see `ProjectOut` / projects router).
9. **Storage:** `STORAGE_BACKEND=auto` uses local disk when AWS keys are placeholders; set real keys + `s3` for cloud.
10. **Rule 5 is LLM-only** — no deterministic regex shortcuts; Groq generates every custom pattern from plain English.
11. **Date cells from Excel are typed values** — never rely on `str(datetime)` alone for format checks.
12. **Validation run `name` is user-supplied and unique per project** — trim on input; empty → 422; unique violation → 409 with a stable detail message.

---

## Open Questions / TBD

- Background job for `execute` (Celery / RQ / FastAPI BackgroundTasks)
- Password reset
- Project switcher UI (backend already supports multiple projects)
- Stricter alignment of auto-created tables with `schema.sql` CHECKs
- Server-side auth (httpOnly cookie) so results can SSR — frontend currently uses Bearer + readable cookie for middleware
- Drop unused `passlib` from `requirements.txt` once confirmed unused

---

## Session Log

### 2026-08-13 — Cross-project runs list

- Added `GET /api/runs/` (optional `project_id`, `limit`, `offset`) joining runs → owned projects for the current user; response includes `project_id` / `project_name` for Activity UI.
- Test: `test_list_runs_across_projects` in `tests/test_run_names.py`.

### 2026-08-13 — Logout endpoint

- Added `POST /api/auth/logout` (Bearer required). Confirms session; client clears JWT (stateless).

### 2026-08-13 — Frontend consumes JWT (no API change)

- Next.js frontend now stores login/register `token`, sends `Authorization: Bearer`, and guards routes with cookie + `GET /api/auth/me`.
- Auth contract unchanged: `POST /api/auth/login|register` → `{ token, user }`, `GET /api/auth/me`.
### 2026-08-13 — Unique user-provided validation run names

- Renamed `validation_runs.run_name` → `name` (`VARCHAR(120) NOT NULL`, no default).
- Added `UNIQUE (project_id, name)` in `schema.sql` + SQLAlchemy model.
- Migration `migrations/001_validation_run_names.sql` backfills duplicate `"New validation run"` rows, then applies NOT NULL + unique.
- `POST /api/runs/?project_id=` accepts `{ name }`; trim/empty → 422; conflict → 409 `"A validation run with this name already exists in this project"`.
- List/result responses keep existing shapes; `name` / `runName` now reflect the stored user name.
- Tests: `tests/test_run_names.py` (create, same-project 409, cross-project allowed, empty 422).

### 2026-08-12 — Windows / Python 3.13 runtime fixes + ProjectOut UUID

- Bumped `psycopg2-binary` to `2.9.11` (wheels for cp313 Windows).
- Added `email-validator`, pinned `httpx==0.27.2` (Groq 0.11 incompatible with httpx 0.28 `proxies` kwarg).
- Replaced passlib hashing with direct `bcrypt` (`auth.py`); pin `bcrypt==4.0.1`.
- Relaxed register/login email validation (no strict `EmailStr`).
- Fixed `GET/POST /api/projects/` 500: coerce project `id` UUID → `str` in router/`ProjectOut`.
- Confirmed upload fails with `InvalidAccessKeyId` until real `AWS_*` / bucket are set in `.env`.

### 2026-08-12 — Schemas package

- Split flat `schemas.py` into `schemas/{auth,projects,validation}.py` + `__init__.py` re-exports.
- Router imports unchanged: `from schemas import ...`.

### 2026-08-12 — Project.md added

- Documented stack, structure, env, data model, API map, services, run instructions.

### 2026-08-13 — Date validation + LLM regex hardening

- **Dates:** Excel `datetime`/`date` cells no longer fail as “Invalid date format” (was caused by `str(value)` → `"2024-05-21 00:00:00"`). Accept typed dates; keep string format list; skip special-char flag for valid date separators.
- **Regex engine:** switched custom-rule matching from `re.match` → `re.fullmatch`; try multiple date string forms for regex on Excel date cells.
- **Groq Rule 5:** stronger system prompt + few-shot examples; strip `^`/`$` from model output. On save rules, re-generate `regex` from `regex_prompt` via Groq when a prompt is present (LLM remains the only generator — no deterministic bypass).
- **Repo:** backend published to https://github.com/Shukla0708/migr8-AI-backend

---

## Change Checklist

- [x] New dependency — `pytest==8.3.3`
- [x] New route or response shape — `POST /api/runs/` body `{ name }`; 409 on duplicate
- [x] Model / `schema.sql` change — `name` + unique `(project_id, name)`; migration `001`
- [ ] New env var / `.env.example`
- [x] Service behavior change (rules, Excel, S3, Groq) — 2026-08-13 date + LLM regex
