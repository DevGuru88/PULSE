"""
doc_pipeline_tool.py
====================
ADK-callable tool functions that bridge the SDLC document pipeline
(generate_templates / fill_template / run_pipeline) into the G-Lang_HR
Lifecycle AI Agent platform.

These functions are registered as ADK FunctionTools on the doc_manager_agent.
They are NOT called directly — the agent decides when to call them based on
the user request and the KB state.

Flow:
  User request / scheduled trigger
    └─ root_agent routes to doc_manager_agent
         ├─ detect_project_stage()  → reads stage.json from GCS KB
         ├─ generate_documents()    → calls run_pipeline with stage filter
         └─ upload_docs_to_gcs()    → uploads DOCX files to the GCS pending-review folder for human approval
  After a reviewer approves a document on the Pulse dashboard '/documents'
  page, the dashboard promotes it into 'rag/docs/' and calls
  refresh_rag_corpus() to re-import the GCS folder into Vertex AI RAG.

Environment variables expected (injected by initial-connector.sh):
  GCS_DATA_BUCKET      — GCS bucket name (e.g. lifecycle-agent-<slug>-data)
  CORPUS_RESOURCE_NAME — Vertex AI RAG corpus resource name
  GOOGLE_CLOUD_PROJECT — GCP project ID
  GOOGLE_CLOUD_LOCATION — GCP region
"""

from __future__ import annotations

import json
import os
import re
import sys
import importlib
import tempfile
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# All recognized SDLC document keys (used for KB look-ups and filtering)
ALL_DOC_KEYS: list[str] = [
    "cpdd", "dor", "architecture", "risk_register",
    "codebase_kb", "dod", "runbook", "sop",
    "sprint_log", "project_explanation",
]

# Filename-substring aliases used to identify which doc_key a stored DOCX in
# the KB belongs to. The pipeline writes files using the canonical OUTPUT_NAMES
# from pipeline/fill_template.py (e.g. ``Definition_of_Ready_<project>_<date>.docx``),
# which do NOT contain the short keys ``dor`` / ``dod``. Doing a naive
# ``doc_key in filename`` check therefore misses those documents and the agent
# wrongly concludes they are missing from the KB and regenerates them on every
# run. Keep this map in sync with OUTPUT_NAMES in pipeline/fill_template.py.
DOC_KEY_ALIASES: dict[str, list[str]] = {
    "cpdd":                ["cpdd"],
    "dor":                 ["definition_of_ready", "dor"],
    "architecture":        ["architecture_and_design", "architecture"],
    "risk_register":       ["risk_register"],
    "codebase_kb":         ["codebase_kb"],
    "dod":                 ["definition_of_done", "dod"],
    "runbook":             ["release_runbook", "runbook"],
    "sop":                 ["sop"],
    "sprint_log":          ["sprint_log", "sprint_retro"],
    "project_explanation": ["project_explanation"],
}

# Canonical filename prefix produced by the pipeline for each doc_key. Used
# when garbage-collecting older approved versions of the same document from
# the live KB folder. Must match OUTPUT_NAMES in pipeline/fill_template.py.
DOC_OUTPUT_PREFIXES: dict[str, str] = {
    "cpdd":                "CPDD",
    "dor":                 "Definition_of_Ready",
    "architecture":        "Architecture_and_Design",
    "risk_register":       "Risk_Register",
    "codebase_kb":         "Codebase_KB_Change_Versioning",
    "dod":                 "Definition_of_Done",
    "runbook":             "Release_Runbook",
    "sop":                 "SOP",
    "sprint_log":          "Sprint_Log",
    "project_explanation": "Project_Explanation_Onboarding_Guide",
}


def doc_key_from_filename(name: str) -> Optional[str]:
    """Return the SDLC doc_key for a stored DOCX filename, or None.

    Matches against DOC_KEY_ALIASES (case-insensitive). Prefers the longest
    matching alias so that, e.g., ``architecture_and_design`` wins over the
    shorter ``architecture`` token when both happen to appear.
    """
    if not name:
        return None
    n = name.lower()
    best_key: Optional[str] = None
    best_len = 0
    for key, aliases in DOC_KEY_ALIASES.items():
        for alias in aliases:
            if alias in n and len(alias) > best_len:
                best_key, best_len = key, len(alias)
    return best_key

# ── Resolve the pipeline directory ──────────────────────────────────────────
# When deployed in Docker, pipeline files are copied to /app/pipeline/
# When running locally, they sit next to this file or in the parent workspace.
_THIS_DIR  = Path(__file__).parent
_PIPELINE_DIRS = [
    _THIS_DIR / "pipeline",              # Docker: /app/pipeline/
    _THIS_DIR.parent,                    # Local dev: workspace root
    _THIS_DIR,                           # Fallback: same dir
]

def _pipeline_dir() -> Path:
    for d in _PIPELINE_DIRS:
        if (d / "run_pipeline.py").exists():
            return d
    raise FileNotFoundError(
        "run_pipeline.py not found. Expected in /app/pipeline/ or workspace root.")


# ════════════════════════════════════════════════════════════
#  TOOL 1 — detect_project_stage
# ════════════════════════════════════════════════════════════

def detect_project_stage(gcs_bucket: str = "") -> dict:
    """Detect the current SDLC stage of the project from the GCS knowledge base.

    Reads gs://<gcs_bucket>/stage.json which stores the current stage.
    Falls back to inferring stage from which DOCX documents are already present
    in GCS (RG docs exist → at least DEV; DoD exists → PRE_RELEASE; etc.).

    Args:
        gcs_bucket: GCS bucket name. Defaults to GCS_DATA_BUCKET env var.

    Returns:
        {
          "stage": "DEV",                  # current SDLC stage key
          "source": "stage.json",          # how it was detected
          "docs_present": ["cpdd","dor"],  # docs already in KB
          "docs_missing": ["codebase_kb"], # docs not yet in KB for this stage
          "updated_at": "2026-03-09T...",  # when stage was last set
          "sprint": 2                      # sprint number if available
        }
    """
    bucket = gcs_bucket or os.environ.get("GCS_DATA_BUCKET", "")
    if not bucket:
        return {"stage": "ALL", "source": "default (no bucket configured)",
                "docs_present": [], "docs_missing": [], "error": "GCS_DATA_BUCKET not set"}

    try:
        from google.cloud import storage as gcs
        client = gcs.Client()
        result = {"stage": "ALL", "source": "inferred", "docs_present": [],
                  "docs_missing": [], "updated_at": None, "sprint": None}

        # ── Try to read stage.json ─────────────────────────────────────────
        try:
            blob = client.bucket(bucket).blob("stage.json")
            stage_data = json.loads(blob.download_as_text())
            result["stage"]      = stage_data.get("current_stage", "ALL")
            result["source"]     = "stage.json"
            result["updated_at"] = stage_data.get("updated_at")
            result["sprint"]     = stage_data.get("sprint")
        except Exception:
            logger.info("stage.json not found or unreadable — inferring stage from docs")

        # ── Infer from which DOCX files are already in GCS ────────────────
        STAGE_ORDER = ["RG", "DEV", "PRE_RELEASE", "POST_LIVE"]
        STAGE_DOCS  = {
            "RG":          ["cpdd", "dor", "architecture", "risk_register"],
            "DEV":         ["codebase_kb"],
            "PRE_RELEASE": ["dod", "runbook"],
            "POST_LIVE":   ["sop"],
        }
        blobs = [b.name for b in client.list_blobs(bucket, prefix="rag/docs/")]
        present = []
        for b in blobs:
            doc_key = doc_key_from_filename(Path(b).name)
            if doc_key:
                present.append(doc_key)
        result["docs_present"] = list(set(present))

        if result["source"] == "inferred":
            # Find the furthest stage all docs are present for
            inferred = "RG"
            for stage_key in STAGE_ORDER:
                stage_docs = STAGE_DOCS[stage_key]
                if all(d in present for d in stage_docs):
                    inferred = stage_key
            result["stage"] = inferred

        # Compute docs_missing: which docs are expected for the current stage but absent
        expected_for_stage = STAGE_DOCS.get(result["stage"], [])
        result["docs_missing"] = [d for d in expected_for_stage
                                   if d not in result["docs_present"]]

        return result

    except ImportError:
        return {"stage": "ALL", "source": "default (google-cloud-storage not installed)",
                "docs_present": [], "docs_missing": [], "error": "gcs SDK not available"}
    except Exception as e:
        logger.error(f"detect_project_stage failed: {e}")
        return {"stage": "ALL", "source": "error", "error": str(e),
                "docs_present": [], "docs_missing": []}


# ════════════════════════════════════════════════════════════
#  TOOL 2 — set_project_stage
# ════════════════════════════════════════════════════════════

def set_project_stage(stage: str, sprint: Optional[int] = None,
                      gcs_bucket: str = "") -> dict:
    """Write the current SDLC stage to gs://<bucket>/stage.json in the KB.

    Call this after a stage transition is confirmed (e.g. all RG docs approved
    → update stage to DEV).

    Args:
        stage:      SDLC stage key: RG | DEV | PRE_RELEASE | POST_LIVE | SPRINT | ONBOARDING
        sprint:     Sprint number (optional, for SPRINT stage)
        gcs_bucket: GCS bucket name. Defaults to GCS_DATA_BUCKET env var.

    Returns:
        {"success": True, "stage": "DEV", "written_to": "gs://bucket/stage.json"}
    """
    bucket = gcs_bucket or os.environ.get("GCS_DATA_BUCKET", "")
    if not bucket:
        return {"success": False, "error": "GCS_DATA_BUCKET not set"}

    valid_stages = {"RG", "DEV", "PRE_RELEASE", "POST_LIVE", "SPRINT", "ONBOARDING", "ALL"}
    if stage.upper() not in valid_stages:
        return {"success": False, "error": f"Invalid stage '{stage}'. Must be one of {valid_stages}"}

    payload = {
        "current_stage": stage.upper(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sprint": sprint,
    }
    try:
        from google.cloud import storage as gcs
        client = gcs.Client()
        blob = client.bucket(bucket).blob("stage.json")
        blob.upload_from_string(json.dumps(payload, indent=2),
                                content_type="application/json")
        return {"success": True, "stage": stage.upper(),
                "written_to": f"gs://{bucket}/stage.json"}
    except ImportError:
        return {"success": False, "error": "google-cloud-storage not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════════════════════
#  TOOL 3 — generate_documents
# ════════════════════════════════════════════════════════════

def generate_documents(
    stage: str = "ALL",
    doc: Optional[str] = None,
    project_name: str = "Project",
    exclude_docs: Optional[list] = None,
) -> dict:
    """Generate SDLC documents for a given stage using the RAG pipeline.

    Imports and calls run_pipeline.run_pipeline() with the specified stage/doc
    filter so only the relevant documents for the current SDLC phase are built.

    Args:
        stage:        SDLC stage key (RG | DEV | PRE_RELEASE | POST_LIVE |
                      SPRINT | ONBOARDING | ALL). Ignored if doc is set.
        doc:          Single document key override (e.g. 'dor', 'architecture').
                      Takes priority over stage.
        project_name: Project name written into DOCX header and filenames.
        exclude_docs: List of document keys to skip (e.g. already fresh in KB).
                      Documents in this list will be filtered out of the results.

    Returns:
        {
          "success": True,
          "stage": "RG",
          "docs_generated": ["cpdd", "dor", "architecture", "risk_register"],
          "files": [{"key": "cpdd", "file": "CPDD_Project_20260309.docx",
                     "path": "/app/...", "size_kb": 39.6}, ...],
          "output_dir": "/app/pipeline/Project_ProjectDocs_20260309"
        }
    """
    try:
        # Sanitize project name: replace spaces and unsafe chars with underscores
        safe_project_name = re.sub(r'[^\w\-]', '_', project_name.strip())
        if not safe_project_name:
            safe_project_name = "Project"

        pipeline_dir = _pipeline_dir()
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))

        # Import (or reload) so late path insertion works
        if "run_pipeline" in sys.modules:
            rp = importlib.reload(sys.modules["run_pipeline"])
        else:
            import run_pipeline as rp

        results = rp.run_pipeline(
            stage=stage.upper(),
            doc=doc.lower() if doc else None,
            project_name=safe_project_name,
        )

        # Filter out documents that are already fresh in the KB
        excluded = set(exclude_docs or [])
        if excluded:
            results = {k: v for k, v in results.items() if k not in excluded}
            logger.info(f"Excluded fresh KB docs from generation: {excluded}")

        files = [
            {
                "key":     k,
                "file":    v["file"],
                "path":    v.get("path", ""),
                "size_kb": round(v["size_kb"], 1),
            }
            for k, v in results.items()
        ]

        # Derive output_dir from actual file paths in results to stay consistent
        # with what run_pipeline() actually created.
        run_date = date.today().strftime("%Y%m%d")
        output_dir = str(pipeline_dir / f"{safe_project_name}_ProjectDocs_{run_date}")

        return {
            "success":        True,
            "stage":          stage.upper(),
            "doc_filter":     doc,
            "docs_generated": list(results.keys()),
            "excluded_docs":  list(excluded),
            "files":          files,
            "output_dir":     output_dir,
        }

    except Exception as e:
        logger.error(f"generate_documents failed: {e}", exc_info=True)
        return {"success": False, "stage": stage, "error": str(e), "docs_generated": []}


# ════════════════════════════════════════════════════════════
#  TOOL 4 — upload_docs_to_gcs
# ════════════════════════════════════════════════════════════

def upload_docs_to_gcs(
    output_dir: str,
    gcs_bucket: str = "",
    gcs_prefix: str = "",
) -> dict:
    """Upload generated DOCX files to the GCS pending-review folder.

    NOTE: This uploads to the **pending review queue**, NOT directly to the
    live RAG knowledge base corpus. A human reviewer must approve each
    document on the Pulse dashboard ('/documents' page) before it is
    promoted into 'rag/docs/' and re-imported into the Vertex AI RAG corpus.
    Do not bypass this review step.

    Args:
        output_dir:  Local directory containing generated DOCX files.
        gcs_bucket:  GCS bucket name. Defaults to GCS_DATA_BUCKET env var.
        gcs_prefix:  GCS object prefix (folder). Defaults to the
                     PENDING_DOCS_FOLDER env var, or 'pending-documents'.

    Returns:
        {"success": True, "uploaded": ["gs://bucket/pending-documents/CPDD_...docx"],
         "count": 4, "review_required": True,
         "review_url": "/documents"}
    """
    bucket = gcs_bucket or os.environ.get("GCS_DATA_BUCKET", "")
    if not bucket:
        return {"success": False, "error": "GCS_DATA_BUCKET not set", "uploaded": []}

    if not gcs_prefix:
        gcs_prefix = os.environ.get("PENDING_DOCS_FOLDER", "pending-documents")

    out_path = Path(output_dir)
    if not out_path.exists():
        return {"success": False, "error": f"output_dir {output_dir!r} does not exist", "uploaded": []}

    docx_files = list(out_path.glob("*.docx"))
    if not docx_files:
        return {"success": False, "error": f"No .docx files found in {output_dir}", "uploaded": []}

    try:
        from google.cloud import storage as gcs
        client = gcs.Client()
        gcs_bucket_obj = client.bucket(bucket)
        uploaded = []
        for docx in docx_files:
            dest = f"{gcs_prefix.rstrip('/')}/{docx.name}"
            blob = gcs_bucket_obj.blob(dest)
            blob.upload_from_filename(str(docx), content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"))
            uploaded.append(f"gs://{bucket}/{dest}")
            logger.info(f"Uploaded: gs://{bucket}/{dest}")

        return {
            "success": True,
            "uploaded": uploaded,
            "count": len(uploaded),
            "review_required": True,
            "review_url": "/documents",
            "message": (
                f"Uploaded {len(uploaded)} document(s) to the pending review "
                f"queue (gs://{bucket}/{gcs_prefix}/). A reviewer must approve "
                "them on the Pulse dashboard '/documents' page before they "
                "are added to the live RAG knowledge base."
            ),
        }

    except ImportError:
        return {"success": False, "error": "google-cloud-storage not installed", "uploaded": []}
    except Exception as e:
        logger.error(f"upload_docs_to_gcs failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "uploaded": []}


# ════════════════════════════════════════════════════════════
#  TOOL 5 — refresh_rag_corpus
# ════════════════════════════════════════════════════════════

def refresh_rag_corpus(
    gcs_bucket: str = "",
    gcs_prefix: str = "rag/docs",
    corpus_uri: str = "",
) -> dict:
    """Re-import documents from GCS into the Vertex AI RAG corpus.

    Call this after upload_docs_to_gcs() so the new/updated documents
    become searchable by the rag_agent immediately.

    Args:
        gcs_bucket:  GCS bucket name. Defaults to GCS_DATA_BUCKET env var.
        gcs_prefix:  GCS prefix/folder containing the DOCX files.
        corpus_uri:  Vertex AI RAG corpus resource name.
                     Defaults to CORPUS_RESOURCE_NAME env var.

    Returns:
        {"success": True, "corpus_uri": "...", "gcs_path": "gs://bucket/rag/docs/"}
    """
    bucket     = gcs_bucket or os.environ.get("GCS_DATA_BUCKET", "")
    corpus     = corpus_uri or os.environ.get("CORPUS_RESOURCE_NAME", "")
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    region     = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not bucket:
        return {"success": False, "error": "GCS_DATA_BUCKET not set"}
    if not corpus:
        return {"success": False, "error": "CORPUS_RESOURCE_NAME not set"}

    gcs_path = f"gs://{bucket}/{gcs_prefix.rstrip('/')}/"

    try:
        import vertexai
        from vertexai import rag
        vertexai.init(project=project_id, location=region)

        rag.import_files(
            corpus_name=corpus,
            paths=[gcs_path],
        )
        return {
            "success":    True,
            "corpus_uri": corpus,
            "gcs_path":   gcs_path,
            "message":    f"Import triggered for {gcs_path} into {corpus}",
        }

    except ImportError:
        return {"success": False, "error": "vertexai SDK not installed"}
    except Exception as e:
        logger.error(f"refresh_rag_corpus failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def delete_rag_files_by_display_name(
    display_names: list[str],
    corpus_uri: str = "",
) -> dict:
    """Delete RagFile entries from the Vertex AI RAG corpus by display name.

    Removing the underlying DOCX from GCS does NOT remove the corresponding
    ``RagFile`` from the corpus — those entries remain searchable until they
    are explicitly deleted via ``rag.delete_file``. Call this helper after
    pruning older approved versions from ``rag/docs/`` so the corpus stops
    surfacing the stale content.

    Args:
        display_names: Basenames (e.g. ``Definition_of_Ready_Foo_20240101.docx``)
                       of the RagFiles to delete. Matching is exact and
                       case-sensitive against ``RagFile.display_name``.
        corpus_uri:    Vertex AI RAG corpus resource name. Defaults to the
                       ``CORPUS_RESOURCE_NAME`` env var.

    Returns:
        ``{"success": True, "deleted": [...], "not_found": [...]}`` on success,
        or ``{"success": False, "error": "..."}`` on failure.
    """
    if not display_names:
        return {"success": True, "deleted": [], "not_found": []}

    corpus     = corpus_uri or os.environ.get("CORPUS_RESOURCE_NAME", "")
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    region     = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not corpus:
        return {"success": False, "error": "CORPUS_RESOURCE_NAME not set"}

    targets = set(display_names)
    deleted: list[str] = []
    errors:  list[str] = []

    try:
        import vertexai
        from vertexai import rag
        vertexai.init(project=project_id, location=region)

        for rag_file in rag.list_files(corpus_name=corpus):
            if rag_file.display_name in targets:
                try:
                    rag.delete_file(name=rag_file.name)
                    deleted.append(rag_file.display_name)
                    logger.info("Deleted RagFile %s (%s) from corpus",
                                rag_file.display_name, rag_file.name)
                except Exception as e:
                    errors.append(f"{rag_file.display_name}: {e}")
                    logger.warning("Failed to delete RagFile %s: %s",
                                   rag_file.name, e)

        not_found = sorted(targets - set(deleted))
        result = {"success": not errors, "deleted": deleted, "not_found": not_found}
        if errors:
            result["error"] = "; ".join(errors)
        return result

    except ImportError:
        return {"success": False, "error": "vertexai SDK not installed"}
    except Exception as e:
        logger.error("delete_rag_files_by_display_name failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════════════════════
#  TOOL 6 — check_document_staleness
# ════════════════════════════════════════════════════════════

def check_document_staleness(
    gcs_bucket: str = "",
    gcs_prefix: str = "rag/docs",
    max_age_days: int = 30,
) -> dict:
    """Check which documents in the KB are stale (older than max_age_days).

    Args:
        gcs_bucket:   GCS bucket. Defaults to GCS_DATA_BUCKET env var.
        gcs_prefix:   GCS folder to scan.
        max_age_days: Documents older than this are flagged as stale.

    Returns:
        {
          "stale_docs": [{"name": "CPDD_...", "age_days": 45, "stage": "RG"}],
          "fresh_docs": [...],
          "total_docs": 10,
          "checked_at": "2026-03-09T..."
        }
    """
    bucket = gcs_bucket or os.environ.get("GCS_DATA_BUCKET", "")
    if not bucket:
        return {"error": "GCS_DATA_BUCKET not set", "stale_docs": [], "fresh_docs": []}

    try:
        from google.cloud import storage as gcs
        from datetime import timezone as tz
        client = gcs.Client()
        now = datetime.now(timezone.utc)

        DOC_STAGE_MAP = {
            "cpdd": "RG", "architecture": "RG", "dor": "RG", "risk_register": "RG",
            "codebase_kb": "DEV", "dod": "PRE_RELEASE", "runbook": "PRE_RELEASE",
            "sop": "POST_LIVE", "sprint_log": "SPRINT", "project_explanation": "ONBOARDING",
        }

        stale, fresh = [], []
        for blob in client.list_blobs(bucket, prefix=f"{gcs_prefix}/"):
            if not blob.name.endswith(".docx"):
                continue
            age_days = (now - blob.updated).days
            doc_name = blob.name.split("/")[-1]
            doc_key = doc_key_from_filename(doc_name)
            doc_stage = DOC_STAGE_MAP.get(doc_key, "UNKNOWN") if doc_key else "UNKNOWN"
            entry = {"name": doc_name, "age_days": age_days,
                     "stage": doc_stage, "gcs_path": f"gs://{bucket}/{blob.name}",
                     "last_updated": blob.updated.isoformat()}
            (stale if age_days > max_age_days else fresh).append(entry)

        return {
            "stale_docs":  stale,
            "fresh_docs":  fresh,
            "total_docs":  len(stale) + len(fresh),
            "max_age_days": max_age_days,
            "checked_at":  now.isoformat(),
        }

    except ImportError:
        return {"error": "google-cloud-storage not installed", "stale_docs": [], "fresh_docs": []}
    except Exception as e:
        return {"error": str(e), "stale_docs": [], "fresh_docs": []}
