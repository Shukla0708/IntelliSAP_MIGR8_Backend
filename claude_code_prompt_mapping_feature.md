# Task: Build the field-mapping feature (with schema + logic changes)

I want to build a "field mapping" feature in this repo, with the schema, response, and
workflow changes listed below.

**Before writing any code, ask me clarifying questions about anything ambiguous below.**
Several items are intentionally underspecified — do not guess silently on those, list them
out and propose your recommended default, then wait for my answer before implementing.
It's fine to batch all your questions into one message.

---

## Changes to implement

### 1. Source field file — new columns
Add two columns to the source field list upload:
- **Key field flag** (is it a key field: yes/no)
- **Datatype** (source field's datatype)

Add header aliases for these the same way existing columns are aliased (e.g. `key field`,
`is key`, `key` / `datatype`, `data type`, `type`).

### 2. Target field file — new columns
Add two columns to the target field list upload:
- **Table description** (description of the SAP table itself, not just the field)
- **Datatype** (target field's datatype)

Same alias-matching approach as existing target columns.

### 3. Response — new metric
Keep the existing response shape, but add a **"Datatype Match Score"** to each candidate
in `prospects`, alongside the existing `semanticSimilarity` and `confidence`.

### 4. Rename `mapping_runs` → `Mappings`, with field changes
| Change | Detail |
|---|---|
| Rename | `run_name` → `mapping_name` |
| Remove | `completed_at` |
| Remove | `created_by` |
| Add | `mapped_fields` (int — count of source fields that were mapped) |
| Add | `last_updated_at` |

(Keep everything else not mentioned — `id`, `project_id`, `status`, `source_filename`,
`source_s3_key`, `target_filename`, `target_s3_key`, `total_source_fields`, `created_at` —
unless you think one of these should also change; ask if unsure.)

### 5. Rename `mapping_results` → `Mapping_Temp`, with field changes
Only these fields remain: `id`, `run_id`, `source_field`.
- `run_id` → renamed `mapping_id`, FK to `Mappings.id`
- Add a new column **`mapping`**: an array of JSON objects, one per top-3 candidate, each
  containing: similarity score, datatype match score, AI reasoning, AI confidence score
  (plus whatever candidate-identity fields are needed to know *which* target field/table
  each entry refers to — see open question below).
- All other old columns (`field_order`, `source_description`, `rank`, `sap_table`,
  `sap_field`, `target_description`, `embedding_score`, `confidence_score`, `reasoning`,
  `created_at`) are removed from the table structure — their data now lives inside the
  `mapping` JSON array instead.

### 6. New table: `Final_Mapping`
Fields given so far: `id`, `mapping_id` (FK to `Mappings.id`).
This is almost certainly incomplete — see open question below before implementing.

### 7. Save flow
- User clicks **"Start Mapping"** → hits the mapping POST route → **create a new row in
  `Mappings`** immediately (before the pipeline runs).
- Once the embed + LLM pipeline finishes and the response is generated → **save results
  into `Mapping_Temp`** (one row per source field, with its `mapping` JSON array).
- **Only when the user confirms the mapping on the frontend** → save the confirmed
  result(s) into `Final_Mapping`.
- This implies a new confirmation endpoint (e.g. `POST /api/mappings/{run_id}/confirm`).

---

## Open questions I'd like you to raise (and propose defaults for) before coding

1. **`Final_Mapping` schema is incomplete.** With only `id` and `mapping_id`, there's no way
   to record *which* source field was matched to *which* target field/table, or which of
   the top-3 candidates the user picked. What should this table actually store per
   confirmed field — e.g. `source_field`, `sap_table`, `sap_field`, chosen candidate's
   scores/reasoning, a FK back to the specific `Mapping_Temp` row, timestamp, confirmed-by
   user? Is confirmation per-field or "confirm the whole run at once"?

2. **Shape of each object inside `Mapping_Temp.mapping` (the JSON array).** Besides
   similarity score, datatype match score, AI reasoning, and AI confidence score, does each
   candidate object also need `sap_table`, `sap_field`, and `target_description` so the
   frontend can render/identify the option? (I'd assume yes, otherwise the candidates are
   anonymous — please confirm.)

3. **Datatype Match Score definition.** Is this a binary exact-match (0 or 100), or a
   graded score based on type-compatibility rules (e.g. CHAR↔STRING partially compatible,
   NUMC↔INT compatible, DATS↔DATE compatible)? If graded, do you want a maintainable
   compatibility table/config, or should I hardcode a reasonable SAP-type compatibility
   matrix as a first pass?

4. **`mapped_fields` definition.** Does "mapped" mean: (a) source fields that received at
   least one candidate from the embedding/LLM step (i.e. computed right after `Mapping_Temp`
   is populated), or (b) source fields the user has actually confirmed into
   `Final_Mapping`? This affects when the counter gets written/updated.

5. **`status` values on `Mappings`.** Reference used `processing | completed | failed`.
   Given the new confirm step, should we add a `confirmed` (or `partially_confirmed`)
   status, or leave status purely about the pipeline run and track confirmation separately
   (e.g. via presence of `Final_Mapping` rows)?

6. **`last_updated_at` trigger points.** Should this update on every write to the
   `Mappings` row only, or also bump whenever a related `Mapping_Temp` row changes or a
   `Final_Mapping` confirmation happens?

7. **Key field flag type.** Boolean column, or a text/enum value (in case source files use
   varied representations like `Y/N`, `X`, `TRUE/FALSE`, `1/0`) that needs normalization
   during parsing?

8. **Re-running a mapping.** If a run is re-triggered for the same project (new
   `Start Mapping` click), should it always create a brand-new `Mappings` row (my default
   assumption per your flow description), or can an existing one be reused/overwritten?

Please answer these (or tell me to just pick sensible defaults) before I touch schema
migrations, models, parsers, or routes.
