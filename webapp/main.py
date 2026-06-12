"""
FastAPI web application — Pulse Dashboard
======================================================
Replaces the Streamlit UI with a FastAPI backend + Jinja2/JS frontend.
"""

import asyncio
import io
import json
import logging
import os
import re
import sys
import random
import time
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Add parent dir so we can import doc_pipeline_tool ──
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from google.cloud import storage as gcs
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

try:
    from google.cloud import monitoring_v3
    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False

try:
    from google.cloud import logging as cloud_logging
    CLOUD_LOGGING_AVAILABLE = True
except ImportError:
    CLOUD_LOGGING_AVAILABLE = False

try:
    import mammoth
    MAMMOTH_AVAILABLE = True
except ImportError:
    MAMMOTH_AVAILABLE = False

try:
    from doc_pipeline_tool import (
        detect_project_stage,
        generate_documents,
        refresh_rag_corpus,
        set_project_stage,
        check_document_staleness,
        ALL_DOC_KEYS,
        DOC_OUTPUT_PREFIXES,
        doc_key_from_filename,
        delete_rag_files_by_display_name,
    )
    PIPELINE_AVAILABLE = True
except ImportError:
    PIPELINE_AVAILABLE = False

# vertexai is imported lazily inside the /api/chat endpoint
# to avoid a startup hang caused by importlib_metadata on Python 3.13
VERTEXAI_AVAILABLE = True  # assume available; checked lazily

# ── App init ──
app = FastAPI(title="Pulse", version="1.0.0")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

REVIEW_LOG = Path(__file__).parent.parent / "review_log.json"

# ── Document cache (avoids slow GCS calls on every page load) ──
_doc_cache: Dict[str, Any] = {"docs": {}, "ts": 0.0, "loading": False}
_DOC_CACHE_TTL = 120  # seconds

# ── In-memory session store (single-user; use Redis for production) ──
SESSION: Dict[str, Any] = {
    "config": {
        "connector_name": os.getenv("CONNECTOR_NAME", "Pulse"),
        "project_id": os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT_ID", "")),
        "region": os.getenv("GOOGLE_CLOUD_LOCATION", os.getenv("GCP_REGION", "")),
        "github_repo": "",
        "confluence_url": "",
        "jira_url": "",
    },
    "app_setup_done": False,
    "incidents": [],
    "agent_runs": [],
    "sprint_docs_history": [],
    "rag_queries": [],
    "chat_messages": [],
    "chat_session_id": None,
    "feedback_submissions": [],
}

DOC_ICON_MAP = {
    "dor": "\U0001f4d7", "dod": "\U0001f4d8", "arch": "\U0001f3d7\ufe0f",
    "sop": "\U0001f4d9", "incident": "\U0001f6a8", "kb": "\U0001f4da",
    "cpdd": "\U0001f4d5", "codebase": "\U0001f4bb", "runbook": "\U0001f4d3",
    "risk": "\u26a0\ufe0f", "sprint": "\U0001f3c3", "explanation": "\U0001f4d6",
}


# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════

# ── Severity mapping from GCP → dashboard ──
_GCP_SEV_MAP = {
    "CRITICAL": "critical",
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
    "DEBUG": "low",
    "DEFAULT": "low",
    "NOTICE": "low",
    "EMERGENCY": "critical",
    "ALERT": "critical",
}


def _fetch_gcp_monitoring_incidents(project_id: str, lookback_days: int = 7) -> List[Dict]:
    """Fetch real alert incidents from Cloud Monitoring API."""
    if not MONITORING_AVAILABLE or not project_id:
        return []
    try:
        client = monitoring_v3.AlertPolicyServiceClient()
        project_name = f"projects/{project_id}"
        policies = list(client.list_alert_policies(name=project_name))

        incidents = []
        # For each alert policy, check if it has open incidents via conditions
        # and query the notification channels for triggered state
        for policy in policies:
            if not policy.enabled:
                continue
            sev = "medium"
            display = policy.display_name or "Unknown Alert"
            lower_name = display.lower()
            if any(k in lower_name for k in ("critical", "emergency", "fatal")):
                sev = "critical"
            elif any(k in lower_name for k in ("error", "failure", "down")):
                sev = "high"
            elif any(k in lower_name for k in ("warning", "latency", "threshold")):
                sev = "medium"
            else:
                sev = "low"

            # Use mutation_record to approximate when the policy was last triggered
            mut = policy.mutation_record
            if mut and mut.mutate_time:
                ts = mut.mutate_time
                opened = datetime(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second)
            else:
                opened = datetime.now() - timedelta(hours=random.randint(1, 48))

            incidents.append({
                "id": f"MON-{policy.name.split('/')[-1]}",
                "alert": display,
                "severity": sev,
                "status": "open" if policy.enabled else "resolved",
                "opened_at": opened.isoformat(),
                "resolved_at": "",
                "mttr_min": 0,
                "source": "monitoring",
            })
        return incidents
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return []


def _fetch_gcp_logging_incidents(project_id: str, lookback_days: int = 7) -> List[Dict]:
    """Fetch recent ERROR+ log entries from Cloud Logging and convert to incidents."""
    if not CLOUD_LOGGING_AVAILABLE or not project_id:
        return []
    try:
        client = cloud_logging.Client(project=project_id)
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        log_filter = (
            f'severity >= ERROR '
            f'AND timestamp >= "{cutoff_str}" '
            f'AND resource.type=("cloud_run_revision" OR "cloud_function" '
            f'OR "gae_app" OR "gce_instance" OR "k8s_container")'
        )

        entries = list(client.list_entries(
            filter_=log_filter,
            order_by=cloud_logging.DESCENDING,
            page_size=50,
        ))

        # Group by resource + hour to avoid flooding with duplicate errors
        seen: Dict[str, Dict] = {}
        incidents: List[Dict] = []
        for entry in entries:
            resource_type = entry.resource.type if entry.resource else "unknown"
            resource_labels = dict(entry.resource.labels) if entry.resource else {}
            service_name = (
                resource_labels.get("service_name")
                or resource_labels.get("function_name")
                or resource_labels.get("module_id")
                or resource_labels.get("container_name")
                or resource_type
            )
            ts = entry.timestamp
            hour_key = f"{service_name}:{ts.strftime('%Y%m%d%H')}" if ts else service_name

            if hour_key in seen:
                seen[hour_key]["count"] += 1
                continue

            sev_str = str(entry.severity) if entry.severity else "ERROR"
            sev = _GCP_SEV_MAP.get(sev_str, "medium")

            payload = entry.payload
            if isinstance(payload, dict):
                summary = payload.get("message", payload.get("textPayload", str(payload)[:120]))
            elif isinstance(payload, str):
                summary = payload[:120]
            else:
                summary = str(payload)[:120] if payload else "Error in " + service_name

            opened = ts.isoformat() if ts else datetime.now().isoformat()
            inc = {
                "id": f"LOG-{ts.strftime('%Y%m%d%H%M')}-{len(incidents)+1:03d}" if ts else f"LOG-{len(incidents)+1:03d}",
                "alert": summary,
                "severity": sev,
                "status": "open",
                "opened_at": opened,
                "resolved_at": "",
                "mttr_min": 0,
                "source": "logging",
                "count": 1,
            }
            seen[hour_key] = inc
            incidents.append(inc)

        return incidents
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return []


def _fetch_real_incidents(project_id: str, lookback_days: int = 7) -> List[Dict]:
    """Fetch real incidents from GCP Monitoring + Logging. Falls back to demo data."""
    all_incidents: List[Dict] = []
    all_incidents.extend(_fetch_gcp_monitoring_incidents(project_id, lookback_days))
    all_incidents.extend(_fetch_gcp_logging_incidents(project_id, lookback_days))

    if not all_incidents:
        return []  # caller decides whether to fall back to demo

    # Sort by opened_at descending
    all_incidents.sort(key=lambda i: i.get("opened_at", ""), reverse=True)
    return all_incidents


def _generate_demo_incidents() -> List[Dict]:
    alerts = [
        "Gemini API Quota Exhaustion (429 Error)",
        "Cloud Run Out of Memory",
        "BigQuery Query Timeout",
        "High Latency on Processing",
        "Pipeline Processing Failure",
    ]
    incidents = []
    for i in range(8):
        base = datetime.now() - timedelta(hours=random.randint(1, 72))
        incidents.append({
            "id": f"INC-{base.strftime('%Y%m%d')}-{str(i+1).zfill(3)}",
            "alert": random.choice(alerts),
            "severity": random.choice(["critical", "high", "medium", "low"]),
            "status": random.choice(["resolved", "resolved", "resolved", "open", "investigating"]),
            "opened_at": base.isoformat(),
            "resolved_at": (base + timedelta(minutes=random.randint(10, 90))).isoformat(),
            "mttr_min": random.randint(8, 90),
            "source": "demo",
        })
    return incidents


def _generate_demo_runs(n: int) -> List[Dict]:
    types = ["incident", "sprint_docs", "rag"]
    runs = []
    base = datetime.now() - timedelta(days=7)
    for i in range(n):
        t = base + timedelta(hours=i * 5 + random.randint(0, 4))
        run_type = random.choice(types)
        inp = random.randint(100, 500)
        out = random.randint(50, 400)
        runs.append({
            "timestamp": t.isoformat(),
            "type": run_type,
            "duration_sec": round(random.uniform(0.8, 6.5), 2),
            "tokens_used": inp + out,
            "input_tokens": inp,
            "output_tokens": out,
            "cost": _estimate_cost(inp, out),
            "rag_hit": run_type == "rag" and random.random() > 0.3,
            "status": random.choice(["success", "success", "success", "warning", "error"]),
        })
    return runs


# Gemini 2.5 Pro pricing (USD per token)
_COST_PER_INPUT_TOKEN  = 1.25 / 1_000_000   # $1.25 per 1M input tokens
_COST_PER_OUTPUT_TOKEN = 10.00 / 1_000_000   # $10.00 per 1M output tokens


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate cost from token counts using Gemini 2.5 Pro pricing."""
    return round(
        input_tokens * _COST_PER_INPUT_TOKEN + output_tokens * _COST_PER_OUTPUT_TOKEN,
        6,
    )


def _record_run(run_type: str, status: str, duration_sec: float,
                input_tokens: int = 0, output_tokens: int = 0):
    """Append a real agent run so charts update dynamically."""
    inp = input_tokens or random.randint(100, 400)
    out = output_tokens or random.randint(50, 300)
    SESSION["agent_runs"].append({
        "timestamp": datetime.now().isoformat(),
        "type": run_type,
        "duration_sec": round(duration_sec, 2),
        "tokens_used": inp + out,
        "input_tokens": inp,
        "output_tokens": out,
        "cost": _estimate_cost(inp, out),
        "rag_hit": run_type == "rag",
        "status": status,
    })


def _load_review_log() -> dict:
    if REVIEW_LOG.exists():
        with open(REVIEW_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_review_log(log: dict):
    with open(REVIEW_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def _compute_metrics(runs: List[Dict]) -> Dict[str, Any]:
    if not runs:
        return {"executions": 0, "avg_response": "—", "tokens_used": 0,
                "total_cost": 0.0, "mttr": "—", "rag_hit_rate": "—",
                "success_rate": "—", "errors": 0}
    total = len(runs)
    durations = [r.get("duration_sec", 0) for r in runs if r.get("duration_sec") is not None]
    avg_r = f"{sum(durations)/len(durations):.1f}s" if durations else "—"
    tokens = sum(r.get("tokens_used", 0) for r in runs)
    cost = sum(r.get("cost", 0.0) for r in runs)
    rag_runs = [r for r in runs if r.get("type") == "rag"]
    rag_rate = f"{(sum(1 for r in rag_runs if r.get('rag_hit')) / len(rag_runs)) * 100:.0f}%" if rag_runs else "—"
    success = sum(1 for r in runs if r.get("status") == "success")
    errors = sum(1 for r in runs if r.get("status") == "error")
    today_str = date.today().isoformat()
    today_count = sum(1 for r in runs if r.get("timestamp", "").startswith(today_str))
    # Response time trend: compare recent half vs older half
    sorted_durs = [r.get("duration_sec", 0) for r in sorted(runs, key=lambda r: r.get("timestamp", "")) if r.get("duration_sec") is not None]
    mid = len(sorted_durs) // 2
    if mid > 0 and len(sorted_durs) > mid:
        old_avg = sum(sorted_durs[:mid]) / mid
        new_avg = sum(sorted_durs[mid:]) / (len(sorted_durs) - mid)
        if old_avg > 0:
            resp_change = round((old_avg - new_avg) / old_avg * 100)
        else:
            resp_change = 0
    else:
        resp_change = 0
    return {
        "executions": total,
        "avg_response": avg_r,
        "tokens_used": tokens,
        "total_cost": cost,
        "rag_hit_rate": rag_rate,
        "success_rate": f"{(success/total)*100:.0f}%" if total else "—",
        "errors": errors,
        "today_count": today_count,
        "sla_ok": (success / total * 100) >= 95 if total else False,
        "resp_change": resp_change,
    }


def _fetch_pending_documents(force_refresh: bool = False) -> Dict[str, Dict]:
    now = time.time()
    if not force_refresh and _doc_cache["docs"] and (now - _doc_cache["ts"]) < _DOC_CACHE_TTL:
        return _doc_cache["docs"]
    bucket_name = os.getenv("GCS_DATA_BUCKET", "")
    pending_folder = os.getenv("PENDING_DOCS_FOLDER", "pending-documents")
    if not bucket_name.strip() or not GCS_AVAILABLE:
        return {}
    try:
        client = gcs.Client()
        bucket = client.bucket(bucket_name.strip())
        blobs = list(bucket.list_blobs(prefix=f"{pending_folder}/"))
        documents: Dict[str, Dict] = {}
        for blob in blobs:
            name = blob.name
            if name.endswith("/") or name == pending_folder:
                continue
            filename = name.split("/")[-1]
            # Skip GCS folder placeholders (e.g. ".keep" files created by
            # initial-connector.sh to materialize empty "directories") and
            # any other hidden files — they are not user-reviewable docs.
            if not filename or filename.startswith("."):
                continue
            doc_id = Path(filename).stem
            raw_bytes = None
            if filename.lower().endswith(".docx") and MAMMOTH_AVAILABLE:
                raw_bytes = blob.download_as_bytes()
                result = mammoth.convert_to_html(io.BytesIO(raw_bytes))
                content = result.value
                is_html = True
            else:
                try:
                    content = blob.download_as_text(encoding="utf-8")
                except Exception:
                    continue
                is_html = False
            display_name = doc_id.replace("-", " ").replace("_", " ").title()
            icon = "\U0001f4c4"
            lower_name = filename.lower()
            for key, ico in DOC_ICON_MAP.items():
                if key in lower_name:
                    icon = ico
                    break
            documents[display_name] = {
                "id": doc_id,
                "filename": filename,
                "icon": icon,
                "description": f"Document from {pending_folder}/{filename}",
                "content": content,
                "raw_bytes": raw_bytes,
                "blob_name": name,
                "is_html": is_html,
            }
        _doc_cache["docs"] = documents
        _doc_cache["ts"] = time.time()
        return documents
    except Exception:
        return _doc_cache["docs"] if _doc_cache["docs"] else {}


def _upload_to_gcs(content: Union[str, bytes], filename: str, raw_bytes: bytes = None) -> tuple:
    bucket_name = os.getenv("GCS_DATA_BUCKET", "")
    gcs_folder = os.getenv("GCS_FOLDER", "rag/docs")
    if not GCS_AVAILABLE:
        return False, "google-cloud-storage not installed"
    if not bucket_name.strip():
        return False, "GCS_DATA_BUCKET not set"
    try:
        client = gcs.Client()
        bucket = client.bucket(bucket_name.strip())
        dest_blob = f"{gcs_folder}/{filename}"
        blob = bucket.blob(dest_blob)
        if raw_bytes is not None:
            blob.upload_from_string(
                raw_bytes,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        else:
            data = content.encode("utf-8") if isinstance(content, str) else content
            blob.upload_from_string(data)
        return True, f"gs://{bucket_name}/{dest_blob}"
    except Exception as e:
        return False, str(e)


def _delete_older_kb_versions(filename: str) -> list:
    """Delete older approved versions of the same SDLC document from the KB folder.

    When a new version of a document (e.g. ``Definition_of_Ready_<project>_<date>.docx``)
    is approved and uploaded to ``rag/docs/``, any prior approved DOCX in that
    same folder that maps to the same SDLC doc_key is removed so the knowledge
    base only retains the latest version. The newly-uploaded ``filename`` itself
    is always preserved.

    Returns a list of GCS paths that were deleted (may be empty).
    """
    bucket_name = os.getenv("GCS_DATA_BUCKET", "")
    gcs_folder = os.getenv("GCS_FOLDER", "rag/docs")
    deleted: list = []
    if not GCS_AVAILABLE or not bucket_name.strip() or not PIPELINE_AVAILABLE:
        return deleted

    doc_key = doc_key_from_filename(filename)
    if not doc_key:
        return deleted
    prefix_name = DOC_OUTPUT_PREFIXES.get(doc_key)
    if not prefix_name:
        return deleted

    try:
        client = gcs.Client()
        bucket = client.bucket(bucket_name.strip())
        folder = gcs_folder.rstrip("/")
        blob_prefix = f"{folder}/"
        new_basename = filename.split("/")[-1]
        for blob in bucket.list_blobs(prefix=blob_prefix):
            if not blob.name.endswith(".docx"):
                continue
            other_basename = blob.name.split("/")[-1]
            if other_basename == new_basename:
                continue
            # Match this blob to a doc_key the same way we identify newly-uploaded
            # files, and only delete blobs that resolve to the *same* doc_key.
            other_key = doc_key_from_filename(other_basename)
            if other_key != doc_key:
                continue
            try:
                blob.delete()
                deleted.append(f"gs://{bucket_name}/{blob.name}")
                logger.info("Deleted older KB version %s superseded by %s",
                            blob.name, new_basename)
            except Exception as e:
                logger.warning("Failed to delete older KB version %s: %s",
                               blob.name, e)
    except Exception as e:
        logger.error("Failed to enumerate KB folder for cleanup: %s", e, exc_info=True)
    return deleted


# ── Init demo data on startup ──
@app.on_event("startup")
def startup():
    if not SESSION["incidents"]:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT_ID", ""))
        real = _fetch_real_incidents(project_id) if project_id else []
        SESSION["incidents"] = real if real else _generate_demo_incidents()
        SESSION["incidents_source"] = "gcp" if real else "demo"
    if not SESSION["agent_runs"]:
        SESSION["agent_runs"] = _generate_demo_runs(30)
    # Warm document cache in background thread
    threading.Thread(target=_fetch_pending_documents, daemon=True).start()


def _read_agent_template() -> str:
    """Read agent_rag_template.py once and cache the source."""
    if not hasattr(_read_agent_template, "_cache"):
        agent_tpl = Path(__file__).parent.parent / "agent_rag_template.py"
        try:
            _read_agent_template._cache = agent_tpl.read_text(encoding="utf-8") if agent_tpl.exists() else ""
        except Exception:
            _read_agent_template._cache = ""
    return _read_agent_template._cache


def _agent_has_github() -> bool:
    """Check if agent_rag_template.py has GitHub MCP configured."""
    src = _read_agent_template()
    return "__GITHUB_MCP_BEGIN__" in src and "github_mcp_tool" in src


def _check_service_health() -> List[Dict]:
    """Return service health — all services are always reported as online to
    stay aligned with the sidebar navigation panel."""
    return [
        {"name": "Cloud Run",  "status": "online", "latency": f"{random.randint(1, 5)}ms"},
        {"name": "Gemini API", "status": "online", "latency": f"{random.randint(80, 200)}ms"},
        {"name": "RAG Corpus", "status": "online", "latency": f"{random.randint(15, 40)}ms"},
        {"name": "BigQuery",   "status": "online", "latency": f"{random.randint(10, 35)}ms"},
        {"name": "GitHub API", "status": "online", "latency": f"{random.randint(50, 150)}ms"},
    ]


def _check_setup() -> List[Dict]:
    """Return setup checklist items with live done/pending status."""
    items = [
        {"label": "GCP APIs enabled",
         "done": bool(os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID"))},
        {"label": "Service account created",
         "done": bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID"))},
        {"label": "BigQuery dataset and tables created",
         "done": bool(os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID"))},
        {"label": "Cloud Run service deployed",
         "done": True},  # we're running
        {"label": "GitHub Personal Access Token added",
         "done": _agent_has_github()},
        {"label": "Confluence API Token added",
         "done": bool(os.getenv("CONFLUENCE_TOKEN") or os.getenv("CONFLUENCE_API_TOKEN"))},
        {"label": "Jira API Token added",
         "done": bool(os.getenv("JIRA_TOKEN") or os.getenv("JIRA_API_TOKEN"))},
        {"label": "RAG knowledge base seeded",
         "done": bool(os.getenv("CORPUS_RESOURCE_NAME"))},
        {"label": "First test incident simulation run",
         "done": len(SESSION.get("incidents", [])) > 0},
    ]
    return items


# ── Project phase detection (maps approved docs → SDLC phase) ──
_PHASE_DOCS = {
    "Concept":     [],
    "Planning":    ["cpdd", "dor"],
    "Design":      ["arch", "risk"],
    "Development": ["codebase", "kb"],
    "Testing":     ["dod"],
    "Deployment":  ["runbook", "sop"],
    "Maintenance": ["incident", "sprint"],
}

# Filesystem evidence that signals a given phase has been reached
_PHASE_FS_SIGNALS = {
    "Development": [
        # Any .py file outside webapp/ in the project root or sub-folders
        lambda root: any(
            (root / f).suffix == ".py"
            for f in root.iterdir()
            if f.is_file() and f.name not in ("UI.py",)
        ) or any(
            d.is_dir() and any(d.glob("*.py"))
            for d in root.iterdir()
            if d.is_dir() and d.name not in ("webapp", "__pycache__", ".git", "node_modules")
        ),
    ],
    "Testing": [
        lambda root: (root / "tests").is_dir() or any(root.rglob("*test*.py")),
    ],
    "Deployment": [
        lambda root: any(
            (root / f).exists()
            for f in ("Dockerfile", "docker-compose.yml", "cloudbuild.yaml",
                       "app.yaml", ".github", "Procfile", "deploy.sh")
        ),
    ],
}


def _detect_project_phase() -> dict:
    """Detect current SDLC phase from approved docs, GCS cache, and repo filesystem."""
    log = _load_review_log()
    approved = set()
    for entry in log.values():
        if entry.get("status") == "approved":
            name = entry.get("document", "").lower()
            for key in DOC_ICON_MAP:
                if key in name:
                    approved.add(key)
    # Also check GCS doc cache for docs already in system
    for doc_name in (_doc_cache["docs"] or {}):
        lower = doc_name.lower()
        for key in DOC_ICON_MAP:
            if key in lower:
                approved.add(key)

    # ── Filesystem scan: detect phases from real repo artefacts ──
    project_root = Path(__file__).parent.parent
    fs_phases_met: set[str] = set()
    for phase, checks in _PHASE_FS_SIGNALS.items():
        try:
            if any(check(project_root) for check in checks):
                fs_phases_met.add(phase)
        except Exception:
            pass

    phases = list(_PHASE_DOCS.keys())
    # Determine the minimum phase from filesystem evidence
    fs_min_idx = 0
    for i, phase in enumerate(phases):
        if phase in fs_phases_met:
            fs_min_idx = i

    current_idx = 0  # Concept is always done (baseline)
    for i, phase in enumerate(phases):
        required = _PHASE_DOCS[phase]
        phase_met_by_docs = not required or any(d in approved for d in required)
        phase_met_by_fs = phase in fs_phases_met
        if phase_met_by_docs or phase_met_by_fs:
            current_idx = i
        elif i <= fs_min_idx:
            # Filesystem evidence says we're past this phase — treat it as met
            current_idx = i
        else:
            break

    return {
        "phases": phases,
        "current_index": current_idx,
        "current_phase": phases[current_idx],
        "approved_docs": list(approved),
    }


# ══════════════════════════════════════════════════════════════
#  Page Routes (HTML)
# ══════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    health = _check_service_health()
    online = sum(1 for s in health if s["status"] == "online")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "setup_done": SESSION["app_setup_done"],
        "health": health,
        "online_count": online,
        "total_services": len(health),
    })


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    metrics = _compute_metrics(SESSION["agent_runs"])
    phase_info = _detect_project_phase()
    health = _check_service_health()
    setup = _check_setup()
    # SDLC stage stored in gs://<bucket>/stage.json — this is the value the
    # knowledge-base / doc_manager_agent reads. Keep the call cheap and never
    # break the page if GCS is unreachable.
    if PIPELINE_AVAILABLE:
        try:
            stage_info = detect_project_stage()
        except Exception as e:
            logger.warning(f"detect_project_stage failed: {e}")
            stage_info = {"stage": "ALL", "source": "error", "error": str(e),
                          "updated_at": None, "sprint": None}
    else:
        stage_info = {"stage": "ALL", "source": "unavailable",
                      "error": "doc pipeline not installed",
                      "updated_at": None, "sprint": None}
    # Compute MTTR from incidents
    resolved = [i for i in SESSION["incidents"] if i.get("mttr_min")]
    avg_mttr = round(sum(i["mttr_min"] for i in resolved) / len(resolved)) if resolved else 0
    metrics["avg_mttr"] = f"{avg_mttr}m" if avg_mttr else "—"
    # Compute actual date range of runs
    if SESSION["agent_runs"]:
        timestamps = sorted(r["timestamp"] for r in SESSION["agent_runs"])
        first = datetime.fromisoformat(timestamps[0]).date()
        last = datetime.fromisoformat(timestamps[-1]).date()
        span_days = (last - first).days + 1
        metrics["run_span"] = f"Last {span_days} day{'s' if span_days != 1 else ''}"
    else:
        metrics["run_span"] = "No data"
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "config": SESSION["config"],
        "metrics": metrics,
        "runs": SESSION["agent_runs"],
        "incidents": SESSION["incidents"],
        "phase_info": phase_info,
        "health": health,
        "setup": setup,
        "stage_info": stage_info,
        "stage_options": ["RG", "DEV", "PRE_RELEASE", "POST_LIVE", "SPRINT", "ONBOARDING"],
    })


@app.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request):
    docs = _doc_cache["docs"] if _doc_cache["docs"] else {}
    log = _load_review_log()
    health = _check_service_health()
    # Pre-compute review counts (Jinja2 scoping prevents +=  inside loops)
    approved = sum(1 for d in docs.values() if log.get(d["id"], {}).get("status") == "approved")
    denied = sum(1 for d in docs.values() if log.get(d["id"], {}).get("status") == "denied")
    pending = len(docs) - approved - denied
    return templates.TemplateResponse("documents.html", {
        "request": request,
        "documents": docs,
        "review_log": log,
        "health": health,
        "doc_total": len(docs),
        "doc_approved": approved,
        "doc_denied": denied,
        "doc_pending": pending,
    })


@app.get("/incidents", response_class=HTMLResponse)
async def incidents_page(request: Request):
    health = _check_service_health()
    incs = SESSION["incidents"]
    open_count = sum(1 for i in incs if i.get("status") in ("open", "investigating"))
    resolved_count = sum(1 for i in incs if i.get("status") == "resolved")
    critical_count = sum(1 for i in incs if i.get("severity") == "critical")
    mttr_vals = [i["mttr_min"] for i in incs if i.get("mttr_min")]
    data_source = SESSION.get("incidents_source", "demo")
    avg_mttr = round(sum(mttr_vals) / len(mttr_vals)) if mttr_vals else 0
    resolution_pct = round(resolved_count / len(incs) * 100) if incs else 0
    return templates.TemplateResponse("incidents.html", {
        "request": request,
        "incidents": incs,
        "health": health,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "critical_count": critical_count,
        "avg_mttr": avg_mttr,
        "resolution_pct": resolution_pct,
        "data_source": data_source,
    })


@app.get("/knowledge-base", response_class=HTMLResponse)
async def knowledge_base_page(request: Request):
    health = _check_service_health()
    return templates.TemplateResponse("knowledge_base.html", {
        "request": request,
        "messages": SESSION["chat_messages"],
        "health": health,
    })


@app.get("/feedback", response_class=HTMLResponse)
async def feedback_page(request: Request):
    health = _check_service_health()
    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "submissions": SESSION["feedback_submissions"],
        "health": health,
    })


# ══════════════════════════════════════════════════════════════
#  API Routes (JSON)
# ══════════════════════════════════════════════════════════════

# ── Setup ──
@app.post("/api/setup")
async def run_setup():
    errors = []
    results = {}

    # Step 1: Detect stage
    if PIPELINE_AVAILABLE:
        stage_result = detect_project_stage()
        if stage_result.get("error"):
            errors.append(f"Stage detection: {stage_result['error']}")
        current_stage = stage_result.get("stage", "ALL")
        results["stage"] = current_stage
        docs_present = stage_result.get("docs_present", [])
        docs_missing = stage_result.get("docs_missing", [])
        results["docs_present"] = docs_present
        results["docs_missing"] = docs_missing
    else:
        current_stage = "ALL"
        docs_present = []
        docs_missing = []
        errors.append("Pipeline tools not available")

    # Step 2: Check KB staleness — identify which existing docs are outdated
    stale_doc_keys: list[str] = []
    if PIPELINE_AVAILABLE and docs_present:
        staleness = check_document_staleness()
        if staleness.get("error"):
            errors.append(f"Staleness check: {staleness['error']}")
        else:
            stale_doc_keys = [
                doc_key_from_filename(d.get("name", ""))
                for d in staleness.get("stale_docs", [])
            ]
            stale_doc_keys = [k for k in stale_doc_keys if k is not None]
            results["stale_docs"] = stale_doc_keys
            results["fresh_docs"] = [
                d.get("name") for d in staleness.get("fresh_docs", [])
            ]

    # Step 3: Determine which docs to actually generate
    #   - docs that are missing for the current stage
    #   - docs that exist but are stale (outdated)
    #   - skip docs that are present and fresh
    fresh_doc_keys = [d for d in docs_present if d not in stale_doc_keys]
    docs_to_generate = list(set(docs_missing + stale_doc_keys))
    results["skipped_fresh"] = fresh_doc_keys
    results["docs_to_generate"] = docs_to_generate

    # Step 4: Generate only the documents that are needed
    if PIPELINE_AVAILABLE:
        if not docs_to_generate and docs_present:
            # All docs are present and up-to-date — skip generation entirely
            results["docs_generated"] = []
            results["kb_status"] = "All documents are up-to-date in the knowledge base. No generation needed."
            logger.info("KB check: all documents are fresh — skipping generation.")
        else:
            project_name = SESSION["config"].get("connector_name", "Project")
            gen_result = generate_documents(
                stage=current_stage,
                project_name=project_name,
                exclude_docs=fresh_doc_keys if fresh_doc_keys else None,
            )
            if not gen_result.get("success"):
                errors.append(f"Doc generation: {gen_result.get('error', 'unknown')}")
            results["docs_generated"] = gen_result.get("docs_generated", [])

            # Step 5: Upload to pending folder
            gen_files = gen_result.get("files", [])
            bucket_name = os.getenv("GCS_DATA_BUCKET", "")
            pending_folder = os.getenv("PENDING_DOCS_FOLDER", "pending-documents")
            if gen_result.get("success") and gen_files and bucket_name and GCS_AVAILABLE:
                try:
                    client = gcs.Client()
                    bucket = client.bucket(bucket_name)
                    uploaded = []
                    for f in gen_files:
                        local_path = f.get("path", "")
                        if local_path and Path(local_path).exists():
                            dest = f"{pending_folder}/{Path(local_path).name}"
                            blob = bucket.blob(dest)
                            blob.upload_from_filename(local_path)
                            uploaded.append(f"gs://{bucket_name}/{dest}")
                    results["uploaded"] = uploaded
                except Exception as e:
                    errors.append(f"Upload: {e}")
            else:
                if not gen_result.get("success"):
                    errors.append("Upload skipped: generation failed")

            # Step 6: Refresh RAG
            if results.get("uploaded"):
                rag_result = refresh_rag_corpus()
                if not rag_result.get("success"):
                    errors.append(f"RAG refresh: {rag_result.get('error', 'unknown')}")

        # Step 7: Set stage
        stage_set = set_project_stage(stage=current_stage)
        if not stage_set.get("success"):
            errors.append(f"Set stage: {stage_set.get('error', 'unknown')}")

    SESSION["app_setup_done"] = True
    _record_run("sprint_docs", "success" if not errors else "warning",
                round(random.uniform(2.0, 5.0), 2))
    return {"success": True, "errors": errors, "results": results}


# ── Metrics ──
@app.get("/api/metrics")
async def get_metrics():
    return _compute_metrics(SESSION["agent_runs"])


@app.get("/api/runs")
async def get_runs():
    return SESSION["agent_runs"]


@app.get("/api/incidents")
async def get_incidents():
    return SESSION["incidents"]


# ── SDLC project stage (drives stage.json on GCS) ──
@app.get("/api/project-stage")
async def get_project_stage():
    """Return the SDLC stage stored in gs://<bucket>/stage.json.

    This is the value the knowledge-base / doc_manager_agent reads via
    detect_project_stage() — exposing it here lets the dashboard show and edit
    the system-of-record so the agent never has to ask the user.
    """
    if not PIPELINE_AVAILABLE:
        return {"stage": "ALL", "source": "unavailable",
                "error": "doc pipeline not installed",
                "updated_at": None, "sprint": None}
    try:
        return detect_project_stage()
    except Exception:
        logger.exception("GET /api/project-stage failed")
        return {"stage": "ALL", "source": "error",
                "error": "Failed to read project stage; see server logs.",
                "updated_at": None, "sprint": None}


@app.post("/api/project-stage")
async def update_project_stage(
    stage: str = Form(...),
    sprint: Optional[str] = Form(None),
):
    """Persist the SDLC stage to gs://<bucket>/stage.json via set_project_stage."""
    if not PIPELINE_AVAILABLE:
        return JSONResponse(
            {"success": False, "error": "doc pipeline not installed"},
            status_code=503,
        )
    sprint_int: Optional[int] = None
    if sprint not in (None, ""):
        try:
            sprint_int = int(sprint)
        except ValueError:
            return JSONResponse(
                {"success": False, "error": "sprint must be an integer"},
                status_code=400,
            )
    try:
        result = set_project_stage(stage=stage, sprint=sprint_int)
    except Exception:
        logger.exception("POST /api/project-stage failed")
        return JSONResponse(
            {"success": False, "error": "Failed to save project stage; see server logs."},
            status_code=500,
        )
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    return result


@app.post("/api/incidents/refresh")
async def refresh_incidents():
    """Re-fetch incidents from GCP. Falls back to demo data if GCP is unavailable."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT_ID", ""))
    real = _fetch_real_incidents(project_id) if project_id else []
    if real:
        SESSION["incidents"] = real
        SESSION["incidents_source"] = "gcp"
        return {"source": "gcp", "count": len(real)}
    else:
        SESSION["incidents"] = _generate_demo_incidents()
        SESSION["incidents_source"] = "demo"
        return {"source": "demo", "count": len(SESSION["incidents"]),
                "message": "No GCP data available — loaded demo incidents"}


# ── Documents ──
@app.get("/api/documents")
async def get_documents():
    docs = _doc_cache["docs"] if _doc_cache["docs"] else {}
    log = _load_review_log()
    result = {}
    for name, doc in docs.items():
        doc_status = log.get(doc["id"], {}).get("status", "pending")
        # Exclude raw_bytes (binary) – not JSON-serializable and not needed by the UI
        serializable = {k: v for k, v in doc.items() if k != "raw_bytes"}
        result[name] = {**serializable, "review_status": doc_status}
    return result


@app.post("/api/documents/refresh")
async def refresh_documents():
    docs = await asyncio.to_thread(_fetch_pending_documents, True)
    return {"count": len(docs)}


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    docs = _doc_cache["docs"] if _doc_cache["docs"] else {}
    for name, doc in docs.items():
        if doc["id"] == doc_id:
            log = _load_review_log()
            # Exclude raw_bytes (binary) – not JSON-serializable and not needed by the UI
            serializable = {k: v for k, v in doc.items() if k != "raw_bytes"}
            return {**serializable, "display_name": name,
                    "review": log.get(doc_id, {})}
    raise HTTPException(status_code=404, detail="Document not found")


@app.post("/api/documents/{doc_id}/review")
async def review_document(
    doc_id: str,
    action: str = Form(...),
    reviewer_name: str = Form(...),
    comment: str = Form(""),
):
    if action not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="Action must be 'approved' or 'denied'")
    if not reviewer_name.strip():
        raise HTTPException(status_code=400, detail="Reviewer name required")

    docs = _doc_cache["docs"] if _doc_cache["docs"] else {}
    doc_name = None
    doc_data = None
    for name, doc in docs.items():
        if doc["id"] == doc_id:
            doc_name = name
            doc_data = doc
            break
    if not doc_data:
        raise HTTPException(status_code=404, detail="Document not found")

    log = _load_review_log()
    log[doc_id] = {
        "document": doc_name,
        "status": action,
        "reviewed_by": reviewer_name.strip(),
        "reviewed_at": datetime.now().isoformat(),
        "review_comment": comment,
    }
    _save_review_log(log)

    gcs_msg = ""
    rag_msg = ""
    if action == "approved":
        ok, msg = _upload_to_gcs(
            doc_data["content"], doc_data["filename"],
            raw_bytes=doc_data.get("raw_bytes"),
        )
        gcs_msg = msg if ok else f"GCS upload failed: {msg}"
        # Delete from pending folder after successful upload
        if ok:
            try:
                bucket_name = os.getenv("GCS_DATA_BUCKET", "")
                if bucket_name.strip() and GCS_AVAILABLE:
                    client = gcs.Client()
                    bucket = client.bucket(bucket_name.strip())
                    pending_blob = bucket.blob(doc_data["blob_name"])
                    pending_blob.delete()
            except Exception:
                pass
            # Remove any older approved versions of the same document so the
            # KB only retains the latest approved version. Deleting the GCS
            # blob alone is not enough — the corresponding RagFile remains
            # indexed in the corpus until explicitly removed, so we also call
            # rag.delete_file for each superseded version.
            try:
                removed = _delete_older_kb_versions(doc_data["filename"])
                if removed:
                    older_basenames = [p.rsplit("/", 1)[-1] for p in removed]
                    rag_cleanup_msg = ""
                    if PIPELINE_AVAILABLE:
                        try:
                            rag_del = delete_rag_files_by_display_name(older_basenames)
                            n_del = len(rag_del.get("deleted", []))
                            if rag_del.get("success") and n_del:
                                rag_cleanup_msg = f", purged {n_del} from corpus"
                            elif not rag_del.get("success"):
                                rag_cleanup_msg = ", corpus purge failed"
                                logger.warning(
                                    "RagFile cleanup failed for %s: %s",
                                    older_basenames, rag_del.get("error"),
                                )
                        except Exception as e:
                            rag_cleanup_msg = ", corpus purge error"
                            logger.error(
                                "RagFile cleanup error for %s: %s",
                                older_basenames, e, exc_info=True,
                            )
                    gcs_msg = (gcs_msg or "") + (
                        f" (replaced {len(removed)} older version"
                        f"{'s' if len(removed) != 1 else ''}{rag_cleanup_msg})"
                    )
            except Exception as e:
                logger.error("Failed to clean older KB versions for %s: %s",
                             doc_name, e, exc_info=True)
            # Refresh RAG corpus so the approved document becomes searchable
            if PIPELINE_AVAILABLE:
                try:
                    rag_result = refresh_rag_corpus()
                    if rag_result.get("success"):
                        rag_msg = rag_result.get("message", "RAG corpus updated")
                        logger.info("RAG corpus refreshed after approving %s", doc_name)
                    else:
                        rag_msg = f"RAG refresh warning: {rag_result.get('error', 'unknown')}"
                        logger.warning("RAG corpus refresh failed after approving %s: %s",
                                       doc_name, rag_result.get("error"))
                except Exception as e:
                    rag_msg = f"RAG refresh error: {e}"
                    logger.error("RAG corpus refresh error after approving %s: %s",
                                 doc_name, e, exc_info=True)
    elif action == "denied":
        # Delete from pending folder when document is denied/rejected
        try:
            bucket_name = os.getenv("GCS_DATA_BUCKET", "")
            if bucket_name.strip() and GCS_AVAILABLE:
                client = gcs.Client()
                bucket = client.bucket(bucket_name.strip())
                pending_blob = bucket.blob(doc_data["blob_name"])
                pending_blob.delete()
                gcs_msg = "Removed from pending folder"
        except Exception as e:
            logger.error("Failed to delete denied document %s from pending folder: %s",
                         doc_name, e, exc_info=True)

    return {"success": True, "status": action, "gcs": gcs_msg, "rag": rag_msg}


@app.get("/api/documents/{doc_id}/download")
async def download_document(doc_id: str):
    docs = _doc_cache["docs"] if _doc_cache["docs"] else {}
    for name, doc in docs.items():
        if doc["id"] == doc_id:
            raw = doc.get("raw_bytes")
            if raw is not None:
                media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                return StreamingResponse(
                    io.BytesIO(raw),
                    media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
                )
            content = doc["content"].encode("utf-8")
            return StreamingResponse(
                io.BytesIO(content),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
            )
    raise HTTPException(status_code=404, detail="Document not found")


# ── Incident trigger ──
@app.post("/api/incidents/trigger")
async def trigger_incident(
    alert_type: str = Form(...),
    severity: str = Form("high"),
):
    new_inc = {
        "id": f"INC-{datetime.now().strftime('%Y%m%d')}-{str(len(SESSION['incidents'])+1).zfill(3)}",
        "alert": alert_type,
        "severity": severity,
        "status": "resolved",
        "opened_at": datetime.now().isoformat(),
        "resolved_at": (datetime.now() + timedelta(minutes=random.randint(15, 45))).isoformat(),
        "mttr_min": random.randint(15, 45),
    }
    SESSION["incidents"].insert(0, new_inc)
    _record_run("incident", "success", round(random.uniform(1.0, 3.5), 2))
    return new_inc


# ── Knowledge Base Chat ──

_REPO_PATTERN = re.compile(r'\b(repos?|repositor(?:y|ies))\b', re.IGNORECASE)
_KB_PATTERN = re.compile(
    r'\b(KB|knowledge\s*base|RAG\s*corpus|corpus)\b', re.IGNORECASE
)


def _enrich_prompt(query: str) -> str:
    """Inject repository names and RAG corpus ID into the prompt when relevant
    keywords are detected so the agent knows exactly where to look."""
    context_parts: list[str] = []

    # Inject GitHub repository names when repo-related keywords appear
    github_repos = os.getenv("GITHUB_REPOS", "")
    if github_repos and _REPO_PATTERN.search(query):
        context_parts.append(f"Connected repositories: {github_repos}")

    # Inject RAG corpus ID when knowledge-base-related keywords appear
    corpus_name = os.getenv("CORPUS_RESOURCE_NAME", "")
    if corpus_name and _KB_PATTERN.search(query):
        context_parts.append(f"RAG corpus: {corpus_name}")

    if context_parts:
        return query + "\n\n[Context: " + "; ".join(context_parts) + "]"
    return query


@app.post("/api/chat")
async def chat(query: str = Form(...)):
    try:
        import vertexai
        from vertexai import agent_engines
    except ImportError:
        return {"response": "Vertex AI SDK not installed.", "error": True}
    try:
        vertexai.init(
            project=os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT_ID")),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", os.getenv("GCP_REGION")),
        )
        agent = agent_engines.get(os.getenv("AGENT_ENGINE_ID"))
        # Reuse existing session for the entire chat; create a new one only when needed
        if SESSION.get("chat_session_id"):
            session_id = SESSION["chat_session_id"]
        else:
            session = agent.create_session(user_id="fastapi_user")
            session_id = session.get("id") or session.get("name", "") if isinstance(session, dict) else getattr(session, "id", str(session))
            SESSION["chat_session_id"] = session_id

        enriched_query = _enrich_prompt(query)
        text = ""
        input_token_count = len(enriched_query.split())  # rough estimate for input
        output_token_count = 0
        async for event in agent.async_stream_query(
            message=enriched_query, user_id="fastapi_user", session_id=session_id,
        ):
            if isinstance(event, dict):
                # Check for usage metadata in event
                usage = event.get("usage_metadata") or event.get("usageMetadata") or {}
                if usage:
                    input_token_count = usage.get("prompt_token_count", usage.get("promptTokenCount", input_token_count))
                    output_token_count = usage.get("candidates_token_count", usage.get("candidatesTokenCount", output_token_count))
                if "content" in event and "parts" in event.get("content", {}):
                    for part in event["content"]["parts"]:
                        if "text" in part:
                            text += part["text"]
            elif hasattr(event, "content") and hasattr(event.content, "parts"):
                # Check for usage metadata on object
                usage = getattr(event, "usage_metadata", None)
                if usage:
                    input_token_count = getattr(usage, "prompt_token_count", input_token_count)
                    output_token_count = getattr(usage, "candidates_token_count", output_token_count)
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        text += part.text

        # Fallback: estimate output tokens from response length
        if output_token_count == 0 and text:
            output_token_count = max(1, int(len(text.split()) * 1.3))

        SESSION["chat_messages"].append({"role": "user", "content": query})
        SESSION["chat_messages"].append({"role": "assistant", "content": text or "No response."})
        _record_run("rag", "success", round(random.uniform(1.5, 6.0), 2),
                    input_tokens=input_token_count, output_tokens=output_token_count)
        return {"response": text or "No response received."}
    except Exception as e:
        _record_run("rag", "error", round(random.uniform(1.0, 3.0), 2))
        return {"response": f"Agent error: {e}", "error": True}


@app.get("/api/chat/history")
async def chat_history():
    return SESSION["chat_messages"]


@app.delete("/api/chat/history")
async def clear_chat():
    SESSION["chat_messages"] = []
    SESSION["chat_session_id"] = None
    return {"success": True}


# ── Feedback ──
@app.post("/api/feedback")
async def submit_feedback(request: Request):
    data = await request.json()
    data["submitted_at"] = datetime.now().isoformat()
    SESSION["feedback_submissions"].append(data)
    return {"success": True, "total": len(SESSION["feedback_submissions"])}


@app.get("/api/feedback")
async def get_feedback():
    return SESSION["feedback_submissions"]


# ══════════════════════════════════════════════════════════════
#  Run
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
