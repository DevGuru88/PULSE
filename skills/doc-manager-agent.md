# Skill: `doc_manager_agent`

## Identity

| Field           | Value                                                                                |
| --------------- | ------------------------------------------------------------------------------------ |
| Agent name      | `doc_manager_agent`                                                                  |
| Type            | Specialist sub-agent (exposed to the `document-editor` root agent via `AgentTool`)   |
| Model           | `gemini-2.5-pro` (with `HttpRetryOptions(attempts=3)`)                               |
| Defined in      | [`agent_rag_template.py`](../agent_rag_template.py) lines 91–170                     |
| Used by         | `document-editor` root agent only. **Not** present in the `security-monitor` build.  |

## Purpose

`doc_manager_agent` is the **SDLC Document Manager**. It owns the full
lifecycle of structured project documents — from discovering what is
already in the knowledge base, through generating the right artifacts for
the current SDLC phase, to submitting them for human review.

The agent **never publishes documents directly into the live RAG corpus**.
Every output is uploaded to a *pending-review* folder in GCS and only
becomes searchable after a reviewer approves it on the `/documents` page of
the Pulse dashboard. The dashboard then promotes the file into
`rag/docs/` and triggers a Vertex AI RAG re-import.

## Tools

The agent is registered with **five `FunctionTool`s** that bridge into
[`doc_pipeline_tool.py`](../doc_pipeline_tool.py). The agent does not call
the underlying pipeline directly — it always goes through these wrappers.

### 1. `detect_project_stage(gcs_bucket="") -> dict`

Reads `gs://$GCS_DATA_BUCKET/stage.json` (set via the dashboard) to determine
the current SDLC stage; falls back to inferring the stage from which DOCX
documents already exist in `rag/docs/`.

Returns:

```json
{
  "stage": "DEV",
  "source": "stage.json",
  "docs_present": ["cpdd","dor"],
  "docs_missing": ["codebase_kb"],
  "updated_at": "2026-03-09T...",
  "sprint": 2
}
```

Recognized stages: `RG`, `DEV`, `PRE_RELEASE`, `POST_LIVE`, `SPRINT`,
`ONBOARDING`, `ALL`.

### 2. `set_project_stage(stage, sprint=None, gcs_bucket="") -> dict`

Writes `stage.json` back to GCS after a confirmed stage transition (e.g.
all RG docs approved → move to `DEV`). Validates `stage` against the set of
recognized values.

### 3. `generate_documents(stage="ALL", doc=None, project_name="Project", exclude_docs=None) -> dict`

Imports and invokes `pipeline/run_pipeline.py::run_pipeline` with the right
filters. The pipeline pulls grounding from the RAG corpus, fills the DOCX
templates produced by `pipeline/generate_templates.py`, and writes
`<Prefix>_<Project>_<YYYYMMDD>.docx` files into a temporary output
directory.

`exclude_docs` is used to skip documents that are already fresh in the KB
(see `check_document_staleness`).

Returns the list of generated files plus the `output_dir` consumed by
`upload_docs_to_gcs`.

### 4. `upload_docs_to_gcs(output_dir, gcs_bucket="", gcs_prefix="") -> dict`

Uploads every `*.docx` in `output_dir` to the **pending-review** folder in
GCS (default `pending-documents/`, overridable through the
`PENDING_DOCS_FOLDER` env var). Returns a payload that includes
`review_required: True` and the `/documents` review URL.

> The agent's instruction explicitly forbids passing a `gcs_prefix` that
> would route documents around the review queue.

### 5. `check_document_staleness(gcs_bucket="", gcs_prefix="rag/docs", max_age_days=30) -> dict`

Lists every DOCX under `rag/docs/` and partitions them into `stale_docs`
(older than `max_age_days`, default 30) and `fresh_docs`, using
`doc_key_from_filename` to map filenames back to canonical document keys.

> **Tools the agent is *not* given.** `refresh_rag_corpus` and
> `delete_rag_files_by_display_name` exist in `doc_pipeline_tool.py` but
> are **deliberately omitted** from the agent's toolset — those operations
> are reserved for the dashboard's review-approval flow.

## SDLC document catalogue

The pipeline supports ten document keys (see `ALL_DOC_KEYS` in
`doc_pipeline_tool.py:45-49` and `DOC_OUTPUT_PREFIXES` lines 74–85):

| Key                    | Output prefix (`DOC_OUTPUT_PREFIXES`) | SDLC stage      |
| ---------------------- | ------------------------------------- | --------------- |
| `cpdd`                 | `CPDD`                                | `RG`            |
| `dor`                  | `Definition_of_Ready`                 | `RG`            |
| `architecture`         | `Architecture_and_Design`             | `RG`            |
| `risk_register`        | `Risk_Register`                       | `RG`            |
| `codebase_kb`          | `Codebase_KB_Change_Versioning`       | `DEV`           |
| `dod`                  | `Definition_of_Done`                  | `PRE_RELEASE`   |
| `runbook`              | `Release_Runbook`                     | `PRE_RELEASE`   |
| `sop`                  | `SOP`                                 | `POST_LIVE`     |
| `sprint_log`           | `Sprint_Log`                          | `SPRINT`        |
| `project_explanation`  | `Project_Explanation_Onboarding_Guide`| `ONBOARDING`    |

The `DOC_KEY_ALIASES` map (lines 58–69) lets `doc_key_from_filename`
correctly recover the key from a stored filename even when the canonical
prefix doesn't contain the short key (e.g. `Definition_of_Ready_*` ↔ `dor`,
`Definition_of_Done_*` ↔ `dod`).

## System instruction (verbatim)

The full instruction sent to the model is defined in
`agent_rag_template.py:97-162`. The high-level structure:

> You are the **SDLC Document Manager Agent** responsible for generating
> and submitting structured project documents for human review.

Followed by these sections:

- **IMPORTANT — Always Check the Knowledge Base First.** Always query the
  RAG corpus (`{CORPUS_URI}`) before generating anything.
- **IMPORTANT — Human Review Is Required.** Generated docs go to GCS
  pending-review only; the dashboard promotes them into `rag/docs/` and
  refreshes the index after approval. Never upload to `rag/docs/`
  directly. Never call a corpus refresh.
- **Responsibilities (8 numbered steps):**
  1. **Detect Stage** — call `detect_project_stage` first.
  2. **Check Staleness** — call `check_document_staleness` (default 30 days).
  3. **Skip Fresh Documents** — present *and* not stale → skip.
  4. **Decide Documents** — pick the right docs for the stage, using the
     mapping below.
  5. **Generate** — call `generate_documents` with `exclude_docs` set to
     the fresh keys to skip.
  6. **Submit for Review** — call `upload_docs_to_gcs(output_dir)`. Do
     **not** pass a custom `gcs_prefix`.
  7. **Notify the User** — explain what was submitted, that it has been
     **sent for review** (not published), and link to `/documents`.
  8. **Stage Transitions** — call `set_project_stage` when the user
     confirms a stage change.
- **Stage → docs map** (mirrored from the catalogue above).
- **Rules:**
  - Never generate documents for a stage other than the one
    `detect_project_stage` returns, unless the user explicitly overrides.
  - Trust the stage returned by the tool; only ask for confirmation when
    the tool returns an explicit `error` or its `source` is
    `"default (no bucket configured)"`.
  - Never bypass the review queue or trigger a corpus refresh directly.
  - Use the `GCS_DATA_BUCKET` env var for all GCS operations.
  - Use the corpus ID `{CORPUS_URI}` for KB look-ups.

`{CORPUS_URI}` is substituted at install time from the
`__CORPUS_RESOURCE_NAME__` placeholder.

## Lifecycle / sequence

```text
User asks for an SDLC update
        │
        ▼
┌────────────────────────┐   1. detect_project_stage()
│  doc_manager_agent     │───────────────────────────────► gs://$BUCKET/stage.json
│                        │   2. check_document_staleness()
│                        │───────────────────────────────► gs://$BUCKET/rag/docs/
│                        │   3. generate_documents(stage, exclude_docs=fresh)
│                        │───────────────────────────────► run_pipeline → DOCX files
│                        │   4. upload_docs_to_gcs(output_dir)
│                        │───────────────────────────────► gs://$BUCKET/pending-documents/
└──────────┬─────────────┘
           │ "Sent for review. Open /documents to approve."
           ▼
   Reviewer on Pulse dashboard
           │ approves
           ▼
   Dashboard moves DOCX into gs://$BUCKET/rag/docs/, refreshes RAG corpus
           ▼
   rag_agent can now retrieve the new content
```

## Inputs and outputs

| Aspect    | Description                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------- |
| Triggers  | User request such as *"Generate the missing RG documents for project Foo"*, or a scheduled run delegated by the root agent. |
| Outputs   | A user-facing message that lists the submitted documents, states they have been **sent for review** (not published), and points the user to `/documents`. |
| Side effects | Writes to `gs://$GCS_DATA_BUCKET/pending-documents/`, optionally writes `gs://$GCS_DATA_BUCKET/stage.json` via `set_project_stage`. |

## Configuration

Environment variables (set in `agent_rag_template.py:30-34` and at deploy
time by `initial-connector.sh`):

- `GOOGLE_CLOUD_PROJECT` — auto-detected from ADC.
- `GOOGLE_CLOUD_LOCATION` — substituted from `__REGION__`.
- `GOOGLE_GENAI_USE_VERTEXAI` — `"True"`.
- `GCS_DATA_BUCKET` — substituted from `__GCS_DATA_BUCKET__`.
- `CORPUS_RESOURCE_NAME` — substituted from `__CORPUS_RESOURCE_NAME__`.
- `PENDING_DOCS_FOLDER` (optional) — overrides the default
  `pending-documents` upload prefix.

Python dependencies added by the connector for this agent: `python-docx`
and `lxml` (used by `pipeline/fill_template.py`).

## Hard rules / guard-rails

- ✋ **Never** upload to `rag/docs/` directly.
- ✋ **Never** call `refresh_rag_corpus` or
  `delete_rag_files_by_display_name` — they are not even in the toolset.
- ✋ **Never** regenerate a document that is present *and* not stale.
- ✅ Always run `detect_project_stage` first.
- ✅ Always run `check_document_staleness` before deciding what to generate.
- ✅ Always link the user to `/documents` after submission.

## See also

- [`document-editor.md`](./document-editor.md) — root agent that delegates
  here.
- [`rag-agent.md`](./rag-agent.md) — the agent that ultimately reads from
  the corpus this agent feeds.
- [`doc_pipeline_tool.py`](../doc_pipeline_tool.py) — implementation of
  every tool listed above.
- [`pipeline/`](../pipeline) — generation pipeline (`run_pipeline.py`,
  `generate_templates.py`, `fill_template.py`, `result_to_docx.py`,
  `rag_prompts.py`).
