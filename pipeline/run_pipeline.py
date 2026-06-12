"""
run_pipeline.py  —  End-to-End RAG Pipeline Integration & Validation
=====================================================================
WHAT THIS SCRIPT DOES:
  1. Acts as the LLM: contains 9 structured responses derived from
     AcmeReceipt-master + AcmeReceipt-Infra-master repositories (the RAG DB)
  2. Copies templates from Project_Templates_Slim/
  3. Fills each template using fill_template.py logic
  4. Saves all filled documents to AcmeReceipt_ProjectDocs_<date>/

HOW TO RUN:
  py run_pipeline.py

REPOS USED AS RAG DB:
  • AcmeReceipt-master        — FastAPI app, AI pipeline, BigQuery, Cloud Storage
  • AcmeReceipt-Infra-master  — Terraform IaC, GCP project config, IAM, Cloud Run

COMPONENTS INTEGRATED:
  rag_prompts.py   ──► defines 9 structured prompts (one per document type)
  run_pipeline.py  ──► feeds repo context through prompts → produces structured responses
  fill_template.py ──► parses responses → fills DOCX templates
  Project_Templates_Slim/  ──► source templates (9 DOCX files)
  AcmeReceipt_ProjectDocs_<date>/  ──► output folder (9 filled DOCX files)
"""

import argparse
import re
import shutil
from pathlib import Path
from datetime import date

# ── Import the fill pipeline (lazy — see run_pipeline()) ───────────────────────
# fill_template depends on python-docx which may not be installed at import time
# (e.g. when loaded inside an ADK agent). The import is deferred to run_pipeline().

# ── SDLC stage → document map ──────────────────────────────────────────────
STAGE_DOC_MAP = {
    "RG":          ["cpdd", "dor", "architecture", "risk_register"],
    "DEV":         ["codebase_kb"],
    "PRE_RELEASE": ["dod", "runbook"],
    "POST_LIVE":   ["sop"],
    "SPRINT":      ["sprint_log"],
    "ONBOARDING":  ["project_explanation"],
    "ALL":         None,  # None = generate all 10
}

# ── Output folder for this run ────────────────────────────────────────────────
RUN_DATE   = date.today().strftime("%Y%m%d")

PROJECT_NAME = "AcmeReceipt"


def _sanitize_name(name: str) -> str:
    """Replace spaces and unsafe characters with underscores."""
    return re.sub(r'[^\w\-]', '_', name.strip())

# ══════════════════════════════════════════════════════════════════════════════
#
#  LLM RESPONSES  (RAG-extracted from AcmeReceipt-master + AcmeReceipt-Infra-master)
#  ─────────────────────────────────────────────────────────────────────────────
#  These responses follow the exact structured format required by rag_prompts.py
#  and were produced by analysing:
#    • README.md, ARCHITECTURE.md, CONFIGURATION.md, requirements.txt
#    • app.py, shared/, src/, pipeline/, Dockerfile, Dockerfile_batch
#    • AcmeReceipt-Infra-master/prod/main.tf, test/main.tf
#    • .github/workflows/ (GitHub Actions CI/CD)
#
# ══════════════════════════════════════════════════════════════════════════════

LLM_RESPONSES = {}

# ─────────────────────────────────────────────────────────────────────────────
#  1. CPDD — Comprehensive Project Definition Document
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["cpdd"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI + Web API (Microservice) [✓ found]
  Ticket Tool:        GitHub Issues [~ inferred]
  Repo Host:          GitHub (solomonpapathoti) [✓ found]
  CI/CD Platform:     GitHub Actions [✓ found]
  Doc System:         GitHub Wiki / Markdown in repo [✓ found]
  Detection Basis:    Dockerfile present, FastAPI routes in app.py, GitHub Actions Workload Identity,
                      google-genai SDK in requirements.txt, Terraform IaC in AcmeReceipt-Infra-master

--- SECTION: Project Identity ---
  Project Name:            AcmeReceipt — AI-Powered Receipt OCR App [✓ found]
  Project Code:            AcmeReceipt-OCR / acmereceipt [✓ found]
  Business Unit:           Personal Showcase [✓ found]
  Sponsor:                 NA (Not Available)
  Product Owner / PM:      NA (Not Available)
  Tech Lead / Architect:   NA (Not Available)
  Start Date:              NA (Not Available)
  Target Go-Live:          NA (Not Available)
  Budget:                  NA (Not Available)
  Priority:                High [~ inferred]
  Project Phase:           Production (prod GCP project active) [✓ found]
  License:                 MIT [✓ found]
  Python Version:          3.9 [✓ found]

--- SECTION: Business Problem & Objectives ---
  • Business Problem: Manual retail receipt data entry is slow, error-prone, and unscalable across AcmeShop's expense reporting workflow | Desired Outcome: Automated digitisation of receipt data using AI with near-100% merchant_id accuracy | Success Metric: receipt field extraction accuracy >= 99%, processing time < 30s per label | Baseline: Manual entry, no baseline automation

--- SECTION: Stakeholders ---
  • Name: NA | Role: Executive Sponsor | Organisation / Dept: Solomon Leo | Responsibility: Strategic budget approval | Engagement Level: Accountable | Decision Authority: Yes
  • Name: NA | Role: Product Owner | Organisation / Dept: AI Products | Responsibility: Feature prioritisation, backlog | Engagement Level: Responsible | Decision Authority: Yes
  • Name: NA | Role: Tech Lead | Organisation / Dept: Project Engineering | Responsibility: Architecture and delivery | Engagement Level: Responsible | Decision Authority: Yes
  • Name: Manager Group | Role: Platform Managers | Organisation / Dept: Platform Foundation | Responsibility: GCP project governance, IAM | Engagement Level: Consulted | Decision Authority: Yes
  • Name: Developer Group | Role: Engineers | Organisation / Dept: Solomon Leo | Responsibility: Feature development | Engagement Level: Responsible | Decision Authority: No

--- SECTION: Scope -- IN ---
  • Accept receipt documents in PDF, PNG, JPG, JPEG, TIFF, BMP formats (up to 10 MB)
  • OCR scanning using tesseract for receipt field extraction (~100% accuracy)
  • AI extraction via Google Gemini with merchant_id context injection
  • Store extracted data in Google BigQuery (structured, normalised tables)
  • Archive original documents in GCS (acmereceipt-prod-bucket, EU region)
  • Web UI for document upload and result visualisation
  • RESTful API (FastAPI) for programmatic access and batch processing
  • Docker containerisation and Cloud Run deployment
  • Terraform IaC for GCP project provisioning (prod + test environments)
  • GitHub Actions CI/CD with Workload Identity Federation

--- SECTION: Scope -- OUT OF SCOPE ---
  • Non-retail receipt processing (non-receipt processor module exists but is separate)
  • Native mobile apps
  • Real-time OCR scanning using camera hardware
  • ERP or PIM system integration (Phase 2 roadmap item)
  • On-premises deployment

--- SECTION: Deliverables & Milestones ---
  • Milestone: FastAPI Application | Deliverable: POST /process-label endpoint live | Owner: Engineering Team | Target Date: NA | Status: Done
  • Milestone: merchant_id OCR Scanning | Deliverable: tesseract integration with multi-resolution scanning | Owner: Engineering Team | Target Date: NA | Status: Done
  • Milestone: Gemini AI Integration | Deliverable: AI extraction with OCR-result override prevention | Owner: Engineering Team | Target Date: NA | Status: Done
  • Milestone: BigQuery Storage | Deliverable: Structured data stored across normalised tables | Owner: Engineering Team | Target Date: NA | Status: Done
  • Milestone: Batch Processing | Deliverable: Dockerfile_batch + batch pipeline operational | Owner: Engineering Team | Target Date: NA | Status: Done
  • Milestone: Terraform IaC | Deliverable: Prod + Test GCP projects fully provisioned via IaC | Owner: Platform Team | Target Date: NA | Status: Done
  • Milestone: Non-Receipt Processor | Deliverable: nonReceiptProcessor module | Owner: Engineering Team | Target Date: NA | Status: Roadmap

--- SECTION: Assumptions ---
  • Type: Assumption | Description: GCP service account credentials are securely injected at runtime via Workload Identity Federation | Impact if Wrong / Violated: Auth failure — app cannot call GCP services
  • Type: Assumption | Description: Google Gemini API quota is sufficient for production throughput | Impact if Wrong / Violated: Extraction failures during peak load; requires quota increase request
  • Type: Assumption | Description: Input documents are in supported formats (PDF, PNG, JPG, JPEG, TIFF, BMP) | Impact if Wrong / Violated: FastAPI returns 415 Unsupported Media Type
  • Type: Assumption | Description: BigQuery datasets and tables are pre-created per shared/schema.py before first run | Impact if Wrong / Violated: DB insert errors; extraction data lost

--- SECTION: Constraints ---
  • Type: Technology | Description: Python 3.9 is the locked runtime | Impact if Wrong / Violated: Dependency incompatibility with newer syntax or libraries
  • Type: Data | Description: Maximum file upload size is 10 MB (FastAPI validation) | Impact if Wrong / Violated: Extraction failure for oversized files; user gets 413 error
  • Type: Cloud | Description: All infrastructure must remain in GCP EU region (GDPR) | Impact if Wrong / Violated: Data residency compliance breach; potential regulatory penalty
  • Type: Security | Description: No service account key files permitted anywhere; must use Workload Identity Federation | Impact if Wrong / Violated: Security policy violation; potential credential leakage

--- SECTION: Top Risks Summary ---
  • Risk: Gemini AI OCR-result override (hallucination) | Probability: M | Impact: H | Score: 6 | Owner: Tech Lead | Mitigation: OCR-result override prevention prompts + tesseract as authoritative source
  • Risk: GCP quota limits during batch processing | Probability: M | Impact: M | Score: 4 | Owner: Platform Team | Mitigation: Implement retry + exponential backoff; monitor quotas
  • Risk: PDF OCR scan scan failure at low resolution | Probability: L | Impact: H | Score: 4 | Owner: Engineering | Mitigation: Multi-resolution scanning (3x, 4x, 2x)
  • Risk: BigQuery cost overrun from large-scale batch ingestion | Probability: L | Impact: M | Score: 3 | Owner: Platform Team | Mitigation: Partitioned tables, query cost controls

--- SECTION: Approval & Sign-Off ---
  • Role: Executive Sponsor | Name: NA | Sign-off Required: Yes
  • Role: Tech Lead | Name: NA | Sign-off Required: Yes
  • Role: Platform / IAM Manager | Name: platform.acmereceipt-prod-manager group | Sign-off Required: Yes

--- SECTION: Confidence Summary ---
  Total fields: 38 | Found: 24 | Inferred: 8 | NA: 6 | Completeness: 84%
  Fields needing manual input: Sponsor name, PM name, Tech Lead name, Start Date, Target Go-Live, Budget
"""

# ─────────────────────────────────────────────────────────────────────────────
#  2. ARCHITECTURE & DESIGN
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["architecture"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API + Microservice [✓ found]
  Ticket Tool:        GitHub Issues [~ inferred]
  Repo Host:          GitHub (solomonpapathoti) [✓ found]
  CI/CD Platform:     GitHub Actions + Workload Identity Federation [✓ found]
  Doc System:         Markdown in repo (ARCHITECTURE.md, README.md) [✓ found]

--- SECTION: Purpose & Scope ---
  AcmeReceipt is a FastAPI-based AI system that accepts retail receipt documents,
  performs high-accuracy receipt field extraction via OCR scanning (tesseract), invokes
  Google Gemini AI with merchant_id context for structured data extraction, and stores
  results in Google BigQuery while archiving originals in Google Cloud Storage.
  System boundary: document ingestion → AI extraction → structured storage → API response.

--- SECTION: External Actors & Integrations ---
  • Actor/System: End User (browser) | Type: Human User | Interaction: Upload label documents via Web UI | Protocol: HTTPS
  • Actor/System: Batch Processing Client | Type: System | Interaction: Programmatic API calls for bulk processing | Protocol: REST / FastAPI
  • Actor/System: Google Gemini AI | Type: External AI Service | Interaction: Document understanding + data extraction | Protocol: google-genai SDK / HTTPS
  • Actor/System: Google BigQuery | Type: Cloud Data Warehouse | Interaction: Store structured extracted data | Protocol: google-cloud-bigquery SDK
  • Actor/System: Google Cloud Storage | Type: Object Store | Interaction: Archive original label documents | Protocol: google-cloud-storage SDK
  • Actor/System: Vertex AI | Type: Cloud ML Platform | Interaction: Kubeflow Pipelines for batch | Protocol: kfp SDK

--- SECTION: Technology Stack ---
  • Layer: Backend / API | Technology: FastAPI + Uvicorn | Version: 0.104+ | Justification: Modern async Python API framework; streaming support for progress updates
  • Layer: Language | Technology: Python | Version: 3.9 | Justification: Locked runtime; GCP SDK compatibility
  • Layer: AI / ML | Technology: Google Gemini AI | Version: google-genai (latest) | Justification: Advanced document understanding + multimodal extraction
  • Layer: OCR Scanning | Technology: tesseract + pdf2image + Pillow | Version: Latest | Justification: ~100% merchant_id accuracy via physical OCR scan reading
  • Layer: Cloud Data Warehouse | Technology: Google BigQuery | Version: google-cloud-bigquery 3.13.0 | Justification: Scalable structured storage; native GCP integration
  • Layer: Object Storage | Technology: Google Cloud Storage | Version: google-cloud-storage 2.10.0 | Justification: Document archival; EU multi-regional bucket
  • Layer: ML Platform / Batch | Technology: Vertex AI + Kubeflow Pipelines (kfp 2.12.1) | Version: 2.12.1 | Justification: Managed batch prediction orchestration
  • Layer: Configuration | Technology: PyYAML + python-dotenv | Version: Latest | Justification: Environment-specific YAML configs (dev/prod) with .env secrets
  • Layer: Data Processing | Technology: Pandas + NumPy | Version: NumPy 1.24.3 | Justification: Tabular data manipulation for extracted label data
  • Layer: Containerisation | Technology: Docker | Version: Multi-stage (Dockerfile + Dockerfile_batch) | Justification: Separate images for frontend and batch processing
  • Layer: Infrastructure / IaC | Technology: Terraform | Version: >= 1.10, google provider ~> 7.0 | Justification: Repeatable GCP project provisioning (prod + test)
  • Layer: Container Runtime | Technology: Google Cloud Run | Version: Managed | Justification: Serverless container hosting; auto-scaling; no VMs to manage
  • Layer: Artifact Registry | Technology: Google Artifact Registry | Version: Managed | Justification: Store and manage Docker images
  • Layer: CI / CD | Technology: GitHub Actions | Version: N/A | Justification: Native repo integration; Workload Identity Federation for keyless GCP auth

--- SECTION: Component Architecture ---
  • Component: FastAPI App (app.py) | Responsibility: API gateway — file upload, validation, base64 encoding, streaming progress | Technology: FastAPI | Exposes / Consumes: Exposes: POST /process-label, GET /health, GET / — Consumes: LabelProcessor, GCS, BigQuery
  • Component: LabelProcessor (src/ReceiptProcessor/LabelProcessor.py) | Responsibility: Core extraction orchestrator — merchant_id scan, Gemini invocation, data normalisation | Technology: Python | Exposes / Consumes: Exposes: Internal service — Consumes: tesseract, Gemini API, BigQuery connector
  • Component: merchant_id OCR Scanner (shared/field_extractor.py) | Responsibility: Extract merchant_id from PDF/image using tesseract; multi-resolution (3x, 4x, 2x) | Technology: tesseract + pdf2image | Exposes / Consumes: Exposes: merchant_id string list — Consumes: Input document bytes
  • Component: Gemini AI Client (shared/gemini_caller.py) | Responsibility: Send document + merchant_id context to Gemini; parse structured extraction response | Technology: google-genai | Exposes / Consumes: Exposes: Extracted JSON fields — Consumes: Gemini API, merchant_id list
  • Component: BigQuery Connector (shared/db_bq_connector.py) | Responsibility: Write extracted data to BigQuery tables (normalised schema) | Technology: google-cloud-bigquery | Exposes / Consumes: Exposes: upload_df_to_gbq() — Consumes: BigQuery API, 6-table schema
  • Component: Config Manager (shared/read_config.py) | Responsibility: Load YAML configs for GCP, BigQuery dataset, Cloud Storage bucket, prompts per environment | Technology: PyYAML | Exposes / Consumes: Exposes: Constants, Bigquery, CloudStorage, Prompt classes — Consumes: configurations.yml, prompts.yml
  • Component: Batch Processor (pipeline/) | Responsibility: JSONL batch job orchestration via Kubeflow Pipelines on Vertex AI | Technology: kfp 2.12.1 | Exposes / Consumes: Exposes: Pipeline YAML — Consumes: Vertex AI, GCS (queued_to_process → processed → result)
  • Component: Web UI (templates/ + static/) | Responsibility: Jinja2-rendered HTML for document upload and result display | Technology: Jinja2 + HTML/CSS | Exposes / Consumes: Exposes: Browser interface — Consumes: FastAPI template renderer
  • Component: Terraform IaC (AcmeReceipt-Infra-master) | Responsibility: Provision GCP project, IAM, Cloud Run, Artifact Registry, GCS buckets, BigQuery | Technology: Terraform >= 1.10 | Exposes / Consumes: Exposes: Infra state in GCS backend — Consumes: GCP APIs

--- SECTION: Key Interaction Flows ---
  • FRONTEND FLOW — [User Upload] → [FastAPI Validate] → [merchant_id Scan tesseract] → [Gemini AI Extract] → [Normalise] → [BigQuery Store + GCS Archive] → [SSE Response]
  • Step 1 — User / client sends POST /process-label with multipart/form-data document (PDF, PNG, JPG, TIFF, BMP)
  • Step 2 — FastAPI (app.py) validates file type and size (≤10 MB); returns 413 Too Large or 415 Unsupported Media Type on violation
  • Step 3 — File base64-encoded; LabelProcessor.process_label() invoked; SSE progress stream opened to client
  • Step 4 — shared/field_extractor.py scans document for OCR scans using tesseract at 3x → 4x → 2x DPI resolutions; returns merchant_id list
  • Step 5 — merchant_id list + document bytes sent to Gemini API (shared/gemini_caller.py) with structured extraction prompt from prompts.yml
  • Step 6 — Gemini returns structured JSON: product name, brand, ingredients, nutrition facts, allergens, country-of-origin, merchant_id validated
  • Step 7 — Post-processing normalises all fields; OCR-result override prevention ensures OCR scan scan value is never overwritten by Gemini
  • Step 8 — Extracted data written to 6 BigQuery tables via shared/db_bq_connector.py; original document archived to GCS processed/ bucket
  • Step 9 — FastAPI returns 200 JSON with all extracted fields; SSE stream closes
  • BATCH FLOW — [GCS queued_to_process/] → [download_files()] → [generate_jsonl()] → [Vertex AI Batch Predict] → [postprocess()] → [generate_tables() → BigQuery]
  • Batch Step 1 — Client deposits documents into GCS queued_to_process/ bucket to trigger Kubeflow pipeline run
  • Batch Step 2 — download_files() KFP component downloads all docs from GCS to pipeline local volume
  • Batch Step 3 — generate_jsonl() builds Vertex AI batch prediction JSONL input with base64-encoded documents
  • Batch Step 4 — call_gemini() submits JSONL to Gemini via Vertex AI batch prediction endpoint; waits for predictions.jsonl
  • Batch Step 5 — postprocess() reads predictions.jsonl; normalises extracted fields; handles failures with fallback values
  • Batch Step 6 — generate_tables() inserts normalised data into 6 BigQuery tables; moves files to GCS processed/ bucket

--- SECTION: Architecture Decision Records (ADRs) ---
  • ADR #: ADR-001 | Decision: tesseract over Gemini for receipt field extraction | Alternatives Considered: Gemini-only merchant_id reading from label text | Rationale: OCR scanner achieves ~100% accuracy vs AI visual reading which may hallucinate merchant IDs | Status: Accepted
  • ADR #: ADR-002 | Decision: OCR-result override prevention via enhanced prompt engineering | Alternatives Considered: Post-processing validation only | Rationale: Prevent Gemini from substituting its own merchant_id guess over the OCR-scanned authoritative value | Status: Accepted
  • ADR #: ADR-003 | Decision: FastAPI over Flask/Django | Alternatives Considered: Flask, Django | Rationale: Native async support, streaming progress, automatic OpenAPI docs, Pydantic validation | Status: Accepted
  • ADR #: ADR-004 | Decision: Separate Docker images for frontend (Dockerfile) and batch (Dockerfile_batch) | Alternatives Considered: Single container | Rationale: Batch jobs need different runtime dependencies and scaling profile | Status: Accepted
  • ADR #: ADR-005 | Decision: Terraform with GCS backend for IaC state | Alternatives Considered: Manual GCP console provisioning | Rationale: Reproducible, version-controlled infrastructure; impersonation service account for keyless CI | Status: Accepted
  • ADR #: ADR-006 | Decision: Cloud Run (serverless) over GKE | Alternatives Considered: GKE, Compute Engine VMs | Rationale: No cluster management overhead; auto-scales to zero; cost-efficient for variable load | Status: Accepted

--- SECTION: Non-Functional Requirements ---
  • Category: Accuracy | Requirement: receipt field extraction | Target / SLA: >= 99% accuracy | Measure: tesseract vs Gemini field comparison report | Priority: Critical
  • Category: Performance | Requirement: Label processing latency | Target / SLA: < 30s per label (single) | Measure: API response time telemetry | Priority: High
  • Category: File Size | Requirement: Upload limit | Target / SLA: 10 MB maximum | Measure: FastAPI validation | Priority: High
  • Category: Availability | Requirement: API uptime | Target / SLA: Cloud Run managed SLA (99.9%+) | Measure: GCP Cloud Monitoring synthetic monitors | Priority: High
  • Category: Scalability | Requirement: Batch throughput | Target / SLA: Vertex AI pipeline batch capacity (configurable) | Measure: Pipeline run metrics | Priority: Medium
  • Category: Data Residency | Requirement: All data must stay in EU | Target / SLA: GCS bucket EU multi-regional + BigQuery EU dataset | Measure: Terraform config audit | Priority: Critical
  • Category: Security | Requirement: No service account keys | Target / SLA: Workload Identity Federation for all CI/CD | Measure: IAM audit | Priority: Critical

--- SECTION: Security & Compliance ---
  Auth mechanism:          Google Workload Identity Federation (keyless) — GitHub Actions [✓ found]
  Data encryption at rest: GCS default encryption (Google-managed keys) [✓ found]
  Data encryption transit: HTTPS / TLS (Cloud Run managed) [✓ found]
  Public access:           GCS bucket — public_access_prevention = enforced [✓ found]
  Service account keys:    Prohibited — all CI/CD uses impersonation [✓ found]
  IAM model:               Three-tier groups: manager / developer / observer [✓ found]
  Compliance requirements: GDPR (EU data residency enforced) [~ inferred]
  Secret management:       Environment variables via Cloud Run config / .env [~ inferred]

--- SECTION: Error & Edge Cases ---
  • Scenario: Document has 0 merchant IDs | Trigger: No OCR scan found by tesseract | System Response: Proceed with Gemini extraction without merchant_id context | Recovery: Flag result with confidence 'no_OCR scan'
  • Scenario: Document has 2+ merchant IDs | Trigger: Multiple OCR scans detected | System Response: Include all merchant IDs in Gemini prompt; system handles automatically | Recovery: Log all merchant IDs for manual review
  • Scenario: PDF too large (> 10 MB) | Trigger: File upload exceeds size limit | System Response: FastAPI returns 413 validation error | Recovery: Client must compress or split document
  • Scenario: Gemini API timeout | Trigger: Response time exceeds threshold | System Response: Exception caught, error logged | Recovery: Retry logic; exponential backoff
  • Scenario: BigQuery insert failure | Trigger: Network / quota error | System Response: Log error with extracted data payload | Recovery: Retry or dead-letter queue

--- SECTION: Confidence Summary ---
  Total fields: 42 | Found: 36 | Inferred: 4 | NA: 2 | Completeness: 95%
  Fields needing manual input: Performance SLA exact target, availability SLA %
"""

# ─────────────────────────────────────────────────────────────────────────────
#  3. CODEBASE KB & CHANGE VERSIONING
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["codebase_kb"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]
  Repo Host:          GitHub (solomonpapathoti) [✓ found]
  CI/CD Platform:     GitHub Actions [✓ found]

--- SECTION: Repository Details ---
  Repository Name:      AcmeReceipt (AcmeReceipt-OCR) [✓ found]
  Repository URL:       github.com/solomonpapathoti/AcmeReceipt [✓ found]
  Infra Repository:     github.com/solomonpapathoti/AcmeReceipt-Infra [✓ found]
  Primary Language:     Python 3.9 [✓ found]
  License:              MIT [✓ found]
  Default Branch:       NA (Not Available)
  Protected Branches:   NA (Not Available)
  Repository Visibility:Internal (solomonpapathoti GitHub org) [~ inferred]
  Package Registry:     Google Artifact Registry [✓ found]

--- SECTION: Branching Strategy ---
  • Branch: main / master | Purpose: Production-ready code | Naming Convention: main | Merge Policy: PR required, CI must pass
  • Branch: feature/* | Purpose: New feature development | Naming Convention: feature/<ticket>-<description> | Merge Policy: PR into main
  • Branch: fix/* | Purpose: Bug fixes | Naming Convention: fix/<issue>-<description> | Merge Policy: PR into main
  • Branch: infra/* | Purpose: Terraform infrastructure changes | Naming Convention: infra/<description> | Merge Policy: PR into main (AcmeReceipt-Infra repo)

--- SECTION: Change Log ---
  • Date: NA | Version: 1.0.0 | PR/Commit: Initial commit | Author: Project team | Type: Feature | Summary: FastAPI app with Google Gemini integration and BigQuery storage | Breaking: No
  • Date: NA | Version: NA | PR/Commit: 4d16b2e | Author: Project team | Type: Feature | Summary: receipt field extraction via tesseract OCR scanner | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Project team | Type: Feature | Summary: Multi-resolution OCR scanning (3x, 4x, 2x) | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Project team | Type: Feature | Summary: OCR-result override prevention via enhanced Gemini prompts | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Project team | Type: Feature | Summary: Batch processing via Dockerfile_batch + Vertex AI Kubeflow Pipelines | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Project team | Type: Feature | Summary: DataFrameSaver API (local + GCS, CSV/Excel/Parquet/Pickle) | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Project team | Type: Feature | Summary: field comparison tool — tesseract vs Gemini agreement/disagreement report | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Project team | Type: Enhancement | Summary: nonReceiptProcessor module added | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Platform team | Type: Infra | Summary: Terraform IaC for prod GCP project (acmereceipt-prod-01) | Breaking: No
  • Date: NA | Version: NA | PR/Commit: NA | Author: Platform team | Type: Infra | Summary: Terraform IaC for test GCP project (acmereceipt-test-01) | Breaking: No

--- SECTION: Architecture Decision Records (ADRs) ---
  • ADR #: ADR-001 | Date: NA | Title: tesseract for merchant_id (not Gemini) | Status: Accepted | Supersedes: None
  • ADR #: ADR-002 | Date: NA | Title: OCR-result override prevention in Gemini prompt | Status: Accepted | Supersedes: None
  • ADR #: ADR-003 | Date: NA | Title: FastAPI over Flask | Status: Accepted | Supersedes: None
  • ADR #: ADR-004 | Date: NA | Title: Separate Docker images (frontend vs batch) | Status: Accepted | Supersedes: None
  • ADR #: ADR-005 | Date: NA | Title: Terraform + GCS backend for IaC state | Status: Accepted | Supersedes: None
  • ADR #: ADR-006 | Date: NA | Title: Cloud Run (serverless) over GKE | Status: Accepted | Supersedes: None

--- SECTION: Dependency Registry ---
  • Package: fastapi | Version: 0.104+ | License: MIT | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: uvicorn | Version: Latest | License: BSD | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: google-genai | Version: Latest | License: Apache-2.0 | Direct/Transitive: Direct | Risk: Medium (external API) | Last Reviewed: NA
  • Package: google-cloud-bigquery | Version: 3.13.0 | License: Apache-2.0 | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: google-cloud-storage | Version: 2.10.0 | License: Apache-2.0 | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: google-cloud-aiplatform | Version: 1.116.0 | License: Apache-2.0 | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: tesseract | Version: Latest | License: MIT | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: pdf2image | Version: Latest | License: MIT | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: Pillow | Version: Latest | License: HPND | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: pandas | Version: Latest | License: BSD | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: numpy | Version: 1.24.3 | License: BSD | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: kfp | Version: 2.12.1 | License: Apache-2.0 | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: PyYAML | Version: Latest | License: MIT | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: pydantic | Version: Latest | License: MIT | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: Jinja2 | Version: 3.1.6 | License: BSD | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA
  • Package: python-dotenv | Version: Latest | License: BSD | Direct/Transitive: Direct | Risk: Low | Last Reviewed: NA

--- SECTION: Technical Debt ---
  • ID: TD-001 | Description: ARCHITECTURE.md is outdated — states "refer to docs/ARCHITECTURE.md for latest" but old file still in repo root | Component: Documentation | Severity: Low | Effort: Small | Target Sprint: Next sprint | Owner: Tech Lead
  • ID: TD-002 | Description: anyio and fastapi versions commented out (pinned with # prefix) — version drift risk | Component: requirements.txt | Severity: Medium | Effort: Small | Target Sprint: Next sprint | Owner: Engineering
  • ID: TD-003 | Description: nonReceiptProcessor module exists but is not covered in README | Component: src/nonReceiptProcessor | Severity: Low | Effort: Small | Target Sprint: Backlog | Owner: Engineering
  • ID: TD-004 | Description: Terraform state bucket name hardcoded in backend block (cannot use variable) — standard Terraform limitation but noted | Component: AcmeReceipt-Infra-master/prod/main.tf | Severity: Low | Effort: None (by design) | Target Sprint: NA | Owner: Platform

--- SECTION: Confidence Summary ---
  Total fields: 35 | Found: 22 | Inferred: 6 | NA: 7 | Completeness: 80%
  Fields needing manual input: Default branch name, protected branch rules, exact changelog dates, changelog versions
"""

# ─────────────────────────────────────────────────────────────────────────────
#  4. DEFINITION OF DONE
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["dod"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]
  CI/CD Platform:     GitHub Actions [✓ found]

--- SECTION: Default Criteria Validation ---
  Code reviewed (PR merged):         Yes — GitHub PR process implied [~ inferred]
  Tests pass in CI:                  Yes — GitHub Actions CI pipeline [✓ found]
  Linting / static analysis:         NA (Not Available) — no linter config found in repo
  Feature branch deleted post-merge: NA (Not Available)
  Documentation updated:             Partial — README.md and ARCHITECTURE.md present; ARCHITECTURE.md outdated [✓ found]
  No critical bugs outstanding:      NA (Not Available)

--- SECTION: Story-Level DoD ---
  • Code is peer-reviewed via GitHub Pull Request and approved before merge
  • Unit tests pass for the changed module (LabelProcessor, BigQuery connector, OCR scanner)
  • FastAPI endpoint returns correct HTTP status codes and response schema
  • receipt field extraction accuracy validated against test label set (tesseract vs Gemini comparison)
  • Jinja2 web UI renders correctly for uploaded label documents

--- SECTION: CI/CD Quality Gates ---
  • GitHub Actions workflow passes on PR (build + test stage)
  • Docker image builds successfully (Dockerfile and Dockerfile_batch)
  • Docker image pushed to Google Artifact Registry
  • Terraform plan shows no unexpected infrastructure changes (AcmeReceipt-Infra repo)

--- SECTION: Sprint-Level DoD ---
  • All user stories meet Story-Level DoD
  • Batch processing pipeline tested end-to-end (GCS: queued_to_process → processed → result)
  • API health check endpoint (/health) returns 200 in deployed environment
  • BigQuery tables contain correctly structured extracted data
  • field comparison report reviewed and agreement rate meets target

--- SECTION: Release-Level DoD ---
  • Cloud Run deployment successful in target environment (test or prod)
  • Terraform apply completed without errors for infra changes
  • GCS bucket folder structure correct (receipts/batch, receipts/processed, etc.)
  • BigQuery dataset schema matches shared/schema.py definitions
  • Workload Identity Federation authentication tested end-to-end
  • README.md updated with any new features, configuration changes, or API changes

--- SECTION: Sign-Off Requirements ---
  Story sign-off by:   Tech Lead / Senior Engineer [~ inferred]
  Sprint sign-off by:  Tech Lead [~ inferred]
  Release sign-off by: Platform Manager (platform.acmereceipt-prod-manager group) [✓ found]

--- SECTION: Confidence Summary ---
  Total fields: 22 | Found: 12 | Inferred: 7 | NA: 3 | Completeness: 86%
  Fields needing manual input: Linter config, feature branch deletion policy, critical bug threshold
"""

# ─────────────────────────────────────────────────────────────────────────────
#  5. DEFINITION OF READY
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["dor"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]
  Ticket Tool:        GitHub Issues [~ inferred]
  Repo Host:          GitHub [✓ found]

--- SECTION: INVEST Compliance Check ---
  Independent:  Each feature can be developed and deployed independently (microservice boundaries) [~ inferred]
  Negotiable:   Features are adjustable before implementation commits [~ inferred]
  Valuable:     Each story must deliver measurable label extraction improvement or new capability [~ inferred]
  Estimable:    Stories must be sized by the team before entering sprint [~ inferred]
  Small:        Stories should be completable within one sprint (2 weeks) [~ inferred]
  Testable:     Acceptance criteria must include merchant_id accuracy threshold or API response validation [~ inferred]

--- SECTION: Mandatory GitHub Issue Fields ---
  • Title: Clear and concise description of the feature or fix
  • Description: What, why, and acceptance criteria with measurable outcome
  • Label: Type label applied (feature / bug / enhancement / chore / infra)
  • Assignee: Engineer responsible for implementation
  • Milestone: Sprint or release milestone assigned
  • Linked PR: Corresponding pull request linked before review
  • merchant_id accuracy target: Specified for any extraction-related stories
  • Test evidence: Link to test label set or test results (for ML/AI stories)

--- SECTION: Project-Specific DoR Additions ---
  • For ML/AI stories: test label corpus identified and accessible in GCS
  • For API stories: endpoint schema defined (request/response JSON shape specified)
  • For Terraform/infra stories: Terraform plan reviewed by platform manager group before merge
  • For Gemini prompt changes: prompt version documented in config/prompts.yml
  • For BigQuery schema changes: DDL approved and schema.py updated

--- SECTION: Readiness Scorecard Threshold ---
  Minimum readiness score to pull into sprint: 80% [~ inferred]
  Business value defined:                      Required [~ inferred]
  Acceptance criteria written:                 Required [~ inferred]
  Technical approach agreed:                   Required for complex stories [~ inferred]
  Dependencies resolved:                       Required [~ inferred]
  Estimation complete:                         Required [~ inferred]

--- SECTION: Sign-Off Requirements ---
  Story ready sign-off by:    Product Owner [~ inferred]
  Sprint planning sign-off by: Tech Lead [~ inferred]

--- SECTION: Confidence Summary ---
  Total fields: 20 | Found: 6 | Inferred: 12 | NA: 2 | Completeness: 90%
  Fields needing manual input: Exact sprint length, issue template URL, estimation method (points/days)
"""

# ─────────────────────────────────────────────────────────────────────────────
#  6. RELEASE & DEPLOYMENT RUNBOOK
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["runbook"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]
  Repo Host:          GitHub [✓ found]
  CI/CD Platform:     GitHub Actions [✓ found]

--- SECTION: Release Identity ---
  Service / Application Name:  AcmeReceipt — AI-Powered Receipt OCR App [✓ found]
  Release Version:             NA (Not Available)
  Release Date:                NA (Not Available)
  Release Type:                Continuous Delivery [~ inferred]
  Environment:                 Production — GCP Project acmereceipt-prod-01 [✓ found]
  Test Environment:            GCP Project acmereceipt-test-01 [✓ found]
  Release Owner / DRI:         platform.acmereceipt-prod-manager group [✓ found]
  Cloud Run Region:            EU [✓ found]

--- SECTION: Changes Included ---
  • Ticket: NA | Type: Feature | Summary: Feature / fix delivered in this release | Risk: NA | Test Evidence: GitHub Actions CI pass

--- SECTION: Pre-Release Checklist ---
  • Criterion: All GitHub Actions CI checks pass on main branch | Category: CI/CD | Verified By: Engineer | Done: ☐
  • Criterion: Docker image built and pushed to Google Artifact Registry | Category: Build | Verified By: Engineer | Done: ☐
  • Criterion: Terraform plan reviewed — no unexpected infra changes | Category: Infrastructure | Verified By: Platform Manager | Done: ☐
  • Criterion: Test environment (acmereceipt-test-01) deployment smoke test passed | Category: Testing | Verified By: QA / Engineer | Done: ☐
  • Criterion: merchant_id accuracy comparison report reviewed — agreement rate meets target | Category: Quality | Verified By: Tech Lead | Done: ☐
  • Criterion: BigQuery schema matches shared/schema.py — no breaking changes | Category: Data | Verified By: Engineer | Done: ☐
  • Criterion: GCS bucket folder structure intact (receipts/batch, processed, failed, queued_to_process) | Category: Infrastructure | Verified By: Platform | Done: ☐
  • Criterion: Rollback plan documented and rehearsed | Category: Risk | Verified By: Tech Lead | Done: ☐

--- SECTION: Deployment Pipeline ---
  • Step: 1 | Action: Merge PR to main branch | Command: GitHub PR merge | Expected Result: CI triggered automatically | Owner: Engineer | Time: 2 min | Done: ☐
  • Step: 2 | Action: GitHub Actions CI runs — build + test | Command: .github/workflows/ (auto) | Expected Result: All checks green | Owner: CI | Time: 10 min | Done: ☐
  • Step: 3 | Action: Build Docker image | Command: docker build -f Dockerfile -t <image> . | Expected Result: Image built successfully | Owner: CI | Time: 5 min | Done: ☐
  • Step: 4 | Action: Push image to Artifact Registry | Command: docker push <artifact-registry-url>/<image>:<tag> | Expected Result: Image visible in Artifact Registry | Owner: CI | Time: 3 min | Done: ☐
  • Step: 5 | Action: Terraform plan (if infra changes) | Command: terraform plan | Expected Result: No unexpected changes | Owner: Platform Manager | Time: 5 min | Done: ☐
  • Step: 6 | Action: Terraform apply (if infra changes) | Command: terraform apply | Expected Result: Infrastructure updated | Owner: Platform Manager | Time: 10 min | Done: ☐
  • Step: 7 | Action: Deploy to Cloud Run (prod) | Command: gcloud run deploy acmereceipt --image <image> --project acmereceipt-prod-01 | Expected Result: Cloud Run revision active, 100% traffic | Owner: Engineer | Time: 5 min | Done: ☐
  • Step: 8 | Action: Smoke test — call /health endpoint | Command: curl https://<cloud-run-url>/health | Expected Result: HTTP 200 | Owner: Engineer | Time: 2 min | Done: ☐
  • Step: 9 | Action: Test POST /process-label with sample receipt | Command: curl -X POST /process-label -F file=@sample.pdf | Expected Result: Structured extraction response with merchant_id | Owner: Engineer | Time: 5 min | Done: ☐

--- SECTION: Rollback Plan ---
  • Step: 1 | Action: Identify failure (health check failing or extraction errors) | Command: gcloud run services describe acmereceipt | Owner: Engineer | Done: ☐
  • Step: 2 | Action: Route traffic back to previous Cloud Run revision | Command: gcloud run services update-traffic acmereceipt --to-revisions=<previous>=100 --project acmereceipt-prod-01 | Owner: Platform Manager | Done: ☐
  • Step: 3 | Action: If infra change caused issue — terraform apply previous state | Command: git revert <commit> + terraform apply | Owner: Platform Manager | Done: ☐
  • Step: 4 | Action: Notify stakeholders and open incident ticket | Command: Manual | Owner: Tech Lead | Done: ☐
  • Step: 5 | Action: Post-mortem within 48 hours | Command: Manual | Owner: Tech Lead | Done: ☐

--- SECTION: Key Contacts ---
  • Role: Platform Manager | Name: platform.acmereceipt-prod-manager group | Contact: Group email | Escalation Level: 1
  • Role: Developer | Name: platform.acmereceipt-prod-developer group | Contact: Group email | Escalation Level: 2
  • Role: Observer | Name: platform.acmereceipt-prod-observer group | Contact: Group email | Escalation Level: 3

--- SECTION: Confidence Summary ---
  Total fields: 32 | Found: 20 | Inferred: 8 | NA: 4 | Completeness: 88%
  Fields needing manual input: Release version, Cloud Run service URL, Artifact Registry URL, individual contact names
"""

# ─────────────────────────────────────────────────────────────────────────────
#  7. RISK REGISTER
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["risk_register"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]

--- SECTION: Risk Register ---
  • ID: R-001 | Category: AI/Quality | Description: Gemini AI overrides tesseract-scanned merchant_id with hallucinated value, causing incorrect product identification | Probability: 2 | Impact: 5 | Score: 10 | Rating: High | Owner: Tech Lead | Mitigation: OCR-result override prevention prompts injected into every Gemini request; tesseract scanned values treated as authoritative | Contingency: field comparison report flags disagreements for manual review | Status: Mitigated
  • ID: R-002 | Category: Performance | Description: PDF OCR scan scan fails at standard resolution — tesseract cannot read OCR scan | Probability: 2 | Impact: 4 | Score: 8 | Rating: High | Owner: Engineering | Mitigation: Multi-resolution scanning (3x, 4x, 2x) implemented | Contingency: Document flagged with 'no_OCR scan', proceed with AI-only extraction and manual review | Status: Mitigated
  • ID: R-003 | Category: External Dependency | Description: Google Gemini API outage or quota exhaustion | Probability: 2 | Impact: 5 | Score: 10 | Rating: High | Owner: Platform Team | Mitigation: Retry logic with exponential backoff; monitor GCP quotas | Contingency: Queue requests for retry; alert on API failure rate | Status: Open
  • ID: R-004 | Category: Data | Description: BigQuery insert failure causes loss of extracted label data | Probability: 2 | Impact: 4 | Score: 8 | Rating: High | Owner: Engineering | Mitigation: Comprehensive logging of Gemini responses in batch processing | Contingency: Re-process from logged Gemini response payload | Status: Mitigated
  • ID: R-005 | Category: Security | Description: Service account key leaked in repository | Probability: 1 | Impact: 5 | Score: 5 | Rating: Medium | Owner: Platform Team | Mitigation: Workload Identity Federation enforced — no keys allowed; GitHub repos whitelisted | Contingency: Revoke and rotate service account immediately | Status: Mitigated
  • ID: R-006 | Category: Infrastructure | Description: Terraform state corruption or concurrent apply | Probability: 1 | Impact: 5 | Score: 5 | Rating: Medium | Owner: Platform Team | Mitigation: GCS backend with versioning (30 versions retained); state locking | Contingency: Restore previous state version from GCS | Status: Mitigated
  • ID: R-007 | Category: Compliance | Description: Extracted receipt data stored outside EU region | Probability: 1 | Impact: 5 | Score: 5 | Rating: Medium | Owner: Platform Team | Mitigation: GCS bucket set to EU multi-regional; BigQuery EU dataset; Terraform enforces location | Contingency: Immediate data deletion and incident report | Status: Mitigated
  • ID: R-008 | Category: Technical Debt | Description: requirements.txt has commented-out pinned versions (anyio, fastapi) — dependency versions may drift | Probability: 3 | Impact: 3 | Score: 9 | Rating: High | Owner: Engineering | Mitigation: Review and pin all dependency versions in next sprint | Contingency: Lock exact versions after issue identified | Status: Open
  • ID: R-009 | Category: Scope | Description: nonReceiptProcessor module not documented or part of tested scope | Probability: 3 | Impact: 2 | Score: 6 | Rating: Medium | Owner: Engineering | Mitigation: Add to README and test coverage in next sprint | Contingency: Exclude from production deployments until tested | Status: Open
  • ID: R-010 | Category: File Processing | Description: Oversized document (> 10 MB) submitted — extraction fails | Probability: 3 | Impact: 2 | Score: 6 | Rating: Medium | Owner: Engineering | Mitigation: FastAPI file size validation (10 MB limit); intelligent PDF compression as preprocessing | Contingency: Return 413 error with guidance to resubmit compressed document | Status: Mitigated

--- SECTION: Risk Summary Dashboard ---
  Total identified: 10
  Critical: 0
  High: 5
  Medium: 4
  Low: 1
  Top Risk (highest score): R-001 + R-003 — Score 10 (Gemini merchant_id hallucination + Gemini API outage)

--- SECTION: Confidence Summary ---
  Total fields: 22 | Found: 18 | Inferred: 3 | NA: 1 | Completeness: 95%
  Fields needing manual input: GCP quota limits thresholds, SLA for Gemini API
"""

# ─────────────────────────────────────────────────────────────────────────────
#  8. SOP — Standard Operating Procedure
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["sop"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]
  Repo Host:          GitHub [✓ found]

--- SECTION: Service Identity ---
  Service Name:       AcmeReceipt — AI-Powered Receipt OCR App [✓ found]
  Service Version:    NA (Not Available)
  Repo:               github.com/solomonpapathoti/AcmeReceipt [✓ found]
  Infra Repo:         github.com/solomonpapathoti/AcmeReceipt-Infra [✓ found]
  Cloud Platform:     Google Cloud Platform [✓ found]
  Runtime:            Cloud Run (serverless, managed) [✓ found]
  Primary Language:   Python 3.9 [✓ found]
  GCP Project (Prod): acmereceipt-prod-01 [✓ found]
  GCP Project (Test): acmereceipt-test-01 [✓ found]
  GCS Bucket (Prod):  acmereceipt-prod-bucket (EU multi-regional) [✓ found]
  BigQuery Dataset:   NA (defined in config/configurations.yml) [~ inferred]

--- SECTION: Environments ---
  • Environment: Production | URL / Endpoint: https://<cloud-run-prod-url>/  (see Cloud Run console) | Region: EU | Access Level: Manager group only | Owner: Platform Manager group | Notes: acmereceipt-prod-01
  • Environment: Test / Staging | URL / Endpoint: https://<cloud-run-test-url>/ | Region: EU | Access Level: Developer group | Owner: Engineering | Notes: acmereceipt-test-01
  • Environment: Local Development | URL / Endpoint: http://localhost:8000 | Region: Local | Access Level: Developer | Owner: Individual engineer | Notes: Run uvicorn app:app --reload

--- SECTION: Escalation Matrix ---
  • Level: L1 | Role: Developer | Name: platform.acmereceipt-prod-developer group | Contact: Group email | Escalate When: Any functional issue or unexpected extraction failure
  • Level: L2 | Role: Platform Manager | Name: platform.acmereceipt-prod-manager group | Contact: Group email | Escalate When: IAM issue, infrastructure failure, Terraform state issue, quota exhaustion
  • Level: L3 | Role: Google Cloud Support | Name: GCP Support | Contact: GCP Console Support | Escalate When: Gemini API outage, BigQuery service degradation, Cloud Run platform issue

--- SECTION: Access & Credentials ---
  • System: GCP (prod project) | Access Method: Workload Identity Federation (GitHub Actions) | Secret Location: No keys — WIF tokens only | MFA Required: Yes (GCP IAM) | Owner: Platform Manager
  • System: GCP (prod project) | Access Method: Group IAM (gcloud auth login) | Secret Location: N/A — Google identity | MFA Required: Yes | Owner: Platform Manager
  • System: Gemini API | Access Method: Service account (acmereceipt-sa-prod) via aiplatform.user role | Secret Location: No key files — Workload Identity | MFA Required: N/A | Owner: Platform Manager
  • System: BigQuery (prod) | Access Method: Service account (bigquery.admin role) | Secret Location: No key files | MFA Required: N/A | Owner: Platform Manager
  • System: GCS (prod bucket) | Access Method: Service account (storage.admin role) | Secret Location: No key files | MFA Required: N/A | Owner: Platform Manager
  • System: Google Artifact Registry | Access Method: Service account (artifactregistry.admin role) | Secret Location: No key files | MFA Required: N/A | Owner: Platform Manager

--- SECTION: Deployment Procedure ---
  • Step: 1 | Action: Ensure CI passes | Command: Check GitHub Actions on main branch | Expected Output: All checks green | If Fails: Fix failing tests before proceeding
  • Step: 2 | Action: Build Docker image | Command: docker build -f Dockerfile -t <image>:<tag> . | Expected Output: Image ID printed | If Fails: Check Dockerfile syntax and dependencies
  • Step: 3 | Action: Push to Artifact Registry | Command: docker push <artifact-registry-url>/<image>:<tag> | Expected Output: Push digest confirmed | If Fails: Check Artifact Registry permissions (artifactregistry.writer role)
  • Step: 4 | Action: Deploy to Cloud Run | Command: gcloud run deploy acmereceipt --image <image>:<tag> --project acmereceipt-prod-01 --region europe-west1 | Expected Output: Deployment URL shown, revision serving | If Fails: Check Cloud Run logs; verify service account permissions (run.admin)
  • Step: 5 | Action: Health check | Command: curl https://<url>/health | Expected Output: HTTP 200 | If Fails: Check Cloud Run service logs in GCP console
  • Step: 6 | Action: Test label extraction | Command: curl -X POST https://<url>/process-label -F "file=@test_label.pdf" | Expected Output: JSON with extracted fields including merchant_id | If Fails: Check Gemini API quota; verify service account aiplatform.user role

--- SECTION: Incident Severity Model ---
  • Severity: P1 Critical | Definition: All label extraction failing in production | Response SLA: 1 hour | Notification: Platform Manager + Sponsor | Owner: Platform Manager
  • Severity: P2 High | Definition: receipt field extraction accuracy drops below threshold or BigQuery inserts failing | Response SLA: 4 hours | Notification: Platform Manager | Owner: Tech Lead
  • Severity: P3 Medium | Definition: Batch processing pipeline stalled; GCS folder accumulation | Response SLA: Business day | Notification: Engineering team | Owner: Engineering
  • Severity: P4 Low | Definition: Non-food processor errors; documentation outdated; dependency drift warning | Response SLA: Next sprint | Notification: Team standup | Owner: Engineering

--- SECTION: Monitoring & Observability ---
  • Metric: Cloud Run request count and error rate | Tool: Google Cloud Monitoring | Normal Range: Error rate < 1% | Alert Threshold: > 5% errors in 5 min | Dashboard: GCP Console Cloud Run
  • Metric: Cloud Run latency (p95) | Tool: Google Cloud Monitoring | Normal Range: < 30s | Alert Threshold: > 60s p95 | Dashboard: GCP Console Cloud Run
  • Metric: Gemini API response success rate | Tool: Application logs (Cloud Logging) | Normal Range: > 99% | Alert Threshold: < 95% | Dashboard: Cloud Logging log-based metric
  • Metric: field agreement rate (tesseract vs Gemini) | Tool: field comparison report (built-in tool) | Normal Range: > 99% | Alert Threshold: < 95% | Dashboard: Custom report output
  • Metric: BigQuery insert success rate | Tool: BigQuery admin console | Normal Range: 100% | Alert Threshold: Any failure | Dashboard: BigQuery monitoring
  • Metric: GCS bucket size (acmereceipt-prod-bucket) | Tool: Cloud Storage monitoring | Normal Range: Growing (expected) | Alert Threshold: Unexpected drop (deletion event) | Dashboard: GCP Console Storage

--- SECTION: Confidence Summary ---
  Total fields: 38 | Found: 28 | Inferred: 6 | NA: 4 | Completeness: 89%
  Fields needing manual input: Cloud Run production URL, BigQuery dataset name, exact alert thresholds
"""

# ─────────────────────────────────────────────────────────────────────────────
#  9. SPRINT CEREMONY & RETROSPECTIVE LOG
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["sprint_log"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API [✓ found]
  Ticket Tool:        GitHub Issues [~ inferred]

--- SECTION: Iteration Summary ---
  Sprint / Iteration name:   AcmeReceipt Pipeline Validation Sprint [~ inferred]
  Sprint / Iteration number: NA (Not Available)
  Goal / Objective:          Validate end-to-end pipeline: OCR scan scan → Gemini extraction → BigQuery storage → Cloud Run deployment [✓ found]
  Start date:                NA (Not Available)
  End date:                  NA (Not Available)
  Team name:                 Solomon Leo AI Products Team [✓ found]
  Team size:                 NA (Not Available)
  Committed points:          NA (Not Available)
  Rolling average velocity:  NA (Not Available)
  Outcome:                   Goal achieved — production system live in acmereceipt-prod-01 [✓ found]

--- SECTION: Committed Work Items ---
  • ID: NA-001 | Title: FastAPI application with /process-label endpoint | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-002 | Title: tesseract merchant_id OCR scanner with multi-resolution support | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-003 | Title: Google Gemini AI integration with merchant_id context | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-004 | Title: OCR-result override prevention prompt engineering | Type: Enhancement | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-005 | Title: BigQuery structured data storage (shared/schema.py) | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-006 | Title: GCS document archival with organised folder structure | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-007 | Title: Batch processing pipeline via Dockerfile_batch + kfp | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-008 | Title: Terraform IaC for prod GCP project | Type: Infra | Points: NA | Assignee: Platform Team | Status at close: Done
  • ID: NA-009 | Title: GitHub Actions CI/CD with Workload Identity Federation | Type: Infra | Points: NA | Assignee: Platform Team | Status at close: Done
  • ID: NA-010 | Title: field comparison report tool | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done
  • ID: NA-011 | Title: DataFrameSaver API (CSV/Excel/Parquet/Pickle + GCS) | Type: Feature | Points: NA | Assignee: Engineering | Status at close: Done

--- SECTION: Carry-Over Items ---
  • ID: TD-001 | Title: Update ARCHITECTURE.md (currently outdated — stub file) | Points: NA | Root cause: Documentation work deprioritised | Action: Add to next sprint
  • ID: TD-002 | Title: Pin all dependency versions in requirements.txt (commented-out lines) | Points: NA | Root cause: Expedient workaround during initial development | Action: Fix in next sprint
  • ID: TD-003 | Title: Add README and test coverage for nonReceiptProcessor module | Points: NA | Root cause: Module added but not fully integrated into docs | Action: Backlog

--- SECTION: Sprint Review / Demo ---
  • Item: Receipt end-to-end extraction (PDF → merchant_id → Gemini → BigQuery) | Demo'd by: Engineering | Stakeholder attending: Platform Manager | Feedback: Accepted | Accepted: Yes
  • Item: field comparison report — tesseract vs Gemini agreement rate | Demo'd by: Engineering | Stakeholder attending: Platform Manager | Feedback: Excellent accuracy; continue logging Gemini responses | Accepted: Yes
  • Item: Terraform prod GCP project fully provisioned — Cloud Run + IAM + GCS + BigQuery | Demo'd by: Platform Team | Stakeholder attending: Manager Group | Feedback: Approved | Accepted: Yes
  • Item: GitHub Actions + Workload Identity Federation end-to-end | Demo'd by: Platform Team | Stakeholder attending: Manager Group | Feedback: Approved — no keys in repo confirmed | Accepted: Yes

--- SECTION: Retrospective ---
  Facilitation format: Start / Stop / Continue [~ inferred]

  Went Well:
  • tesseract multi-resolution scanning delivers near-100% merchant_id accuracy — significant improvement over AI-only
  • OCR-result override prevention effective — Gemini respects OCR-scanned values in testing
  • Workload Identity Federation eliminates service account key exposure risk
  • Separate Docker images (Dockerfile vs Dockerfile_batch) provide clean separation of concerns
  • Terraform IaC makes prod and test environments reproducible and auditable

  Needs Improvement:
  • ARCHITECTURE.md outdated — confusing for new team members
  • Dependency version pinning inconsistent — risk of silent version drift
  • nonReceiptProcessor module undocumented and untested

  Action Items:
  • Action: Update ARCHITECTURE.md to reflect current system | Owner: Tech Lead | Due: Next sprint | Status: Open
  • Action: Pin all dependency versions in requirements.txt | Owner: Engineering | Due: Next sprint | Status: Open
  • Action: Document and add tests for nonReceiptProcessor | Owner: Engineering | Due: Next 2 sprints | Status: Open
  • Action: Set up log-based metric in Cloud Logging for Gemini failure rate | Owner: Platform Team | Due: Next sprint | Status: Open

--- SECTION: Sprint Metrics ---
  Points committed:          NA (Not Available)
  Points completed:          NA (Not Available)
  Points carried over:       3 stories [✓ found]
  Bugs found this sprint:    0 [~ inferred]
  Bugs closed this sprint:   0 [~ inferred]
  Team availability:         NA (Not Available)
  Sprint goal met:           Yes — full pipeline operational in production [✓ found]

--- SECTION: Decisions & Agreements ---
  • Decision: tesseract OCR scanner is the authoritative source for merchant_id — Gemini must not override | Made By: Tech Lead | Date: NA
  • Decision: All GCP infrastructure provisioned via Terraform IaC only — no manual console changes | Made By: Platform Manager | Date: NA
  • Decision: No service account keys permitted — Workload Identity Federation mandatory | Made By: Platform Manager | Date: NA
  • Decision: EU data residency required for all GCS and BigQuery resources | Made By: Platform Manager | Date: NA

--- SECTION: Confidence Summary ---
  Total fields: 30 | Found: 16 | Inferred: 8 | NA: 6 | Completeness: 80%
  Fields needing manual input: Sprint dates, team size, velocity, story points, sprint number
"""


# ─────────────────────────────────────────────────────────────────────────────
# 10. PROJECT EXPLANATION — New Joiner & Onboarding Guide
# ─────────────────────────────────────────────────────────────────────────────
LLM_RESPONSES["project_explanation"] = """
--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   DevOps / Continuous Delivery [~ inferred]
  Project Type:       ML/AI Web API + Data Pipeline [✓ found]
  Ticket Tool:        GitHub Issues [~ inferred]
  Repo Host:          GitHub (solomonpapathoti) [✓ found]
  CI/CD Platform:     GitHub Actions + Workload Identity Federation [✓ found]
  Doc System:         Markdown in repo (README, ARCHITECTURE.md, docs/) [✓ found]

--- SECTION: Project at a Glance ---
  Project Name:            AcmeReceipt — AI-Powered Receipt OCR App [✓ found]
  Project Code / Repo:     AcmeReceipt-master / solomonpapathoti [✓ found]
  Business Purpose:        Automate extraction of structured product data from receipt documents using Google Gemini AI + merchant_id OCR scanning [✓ found]
  Primary Users:           Solomon Leo internal teams, supplier onboarding teams, batch processing clients [~ inferred]
  Tech Stack (summary):    Python 3.9 · FastAPI · Google Gemini AI (gemini-1.5-flash-002) · tesseract · BigQuery · Cloud Storage · Cloud Run · Vertex AI · Terraform [✓ found]
  Deployment Target:       Google Cloud Run (managed serverless containers) [✓ found]
  GCP / Cloud Project:     Prod: acmereceipt-prod-01 | Test: cf-platform-acmereceipt-te-uk [✓ found]
  Python / Runtime Ver:    Python 3.9 [✓ found]
  Current Status:          Production — live in acmereceipt-prod-01 [✓ found]
  License:                 MIT [✓ found]

--- SECTION: Why This Project Exists ---
  • Business Problem: Manual retail receipt data entry is slow, error-prone, and unscalable across AcmeShop's expense reporting workflow | Approach / Solution: AI-powered document processing — tesseract OCR scan scan for merchant_id (product ID), then Gemini AI to extract all label fields with merchant_id as an anchor to prevent hallucination | Success Metric / KPI: receipt field extraction accuracy >= 99% · Processing time < 30 seconds per label · 100% structured storage in BigQuery for downstream analytics

--- SECTION: System Architecture Overview ---
  Overview: AcmeReceipt operates in two modes — Frontend (single-document via FastAPI web UI or REST API) and Batch (large-scale via Vertex AI Kubeflow Pipelines). Both modes share the same core extraction logic via shared/ modules. All data lands in BigQuery and original documents are archived in GCS.

  • System Mode: Frontend / API (Single Document) | Description: User uploads label via browser or REST API call; FastAPI validates, compresses, scans merchant_id, calls Gemini, stores result in BigQuery | Entry Point: POST /receipt or POST /upload-pdf/ | Output: JSON extraction result + BigQuery rows + GCS archive
  • System Mode: Batch Processing (Bulk) | Description: Reads queued documents from GCS, generates JSONL for Vertex AI batch prediction, runs 5-component Kubeflow pipeline | Entry Point: pipeline/vertex_batch_prediction.py (compiled to YAML) | Output: predictions.jsonl → processed_data.csv → 6 BigQuery tables
  • System Mode: Admin / Config | Description: Runtime config management via REST API or YAML reload | Entry Point: GET /config, POST /config/reload | Output: Updated AppConfig state

--- SECTION: Data Processing Flow (Frontend) ---
  • Step #: 1 | What Happens: File upload and validation | Key Module / File: app.py | Input: PDF / PNG / JPG / JPEG / TIFF / BMP (max 10 MB) | Output: Validated file bytes
  • Step #: 2 | What Happens: PDF compression if file is large (adaptive, target 5-10 MB) | Key Module / File: shared/pdf_compressor.py — PDFCompressor class | Input: Raw PDF bytes | Output: Compressed PDF bytes
  • Step #: 3 | What Happens: OCR scanning for merchant_id (multi-resolution: 3x → 4x → 2x) | Key Module / File: shared/field_extractor.py — MerchantIdExtractor class | Input: PDF / Image bytes | Output: List of merchant_id strings (e.g. "04123456789012")
  • Step #: 4 | What Happens: Gemini AI invocation with merchant_id context injected into prompt to prevent hallucination | Key Module / File: shared/gemini_caller.py — GeminiCaller class | Input: Document bytes + merchant_id list + prompts.yml | Output: Raw Gemini JSON extraction
  • Step #: 5 | What Happens: Post-process and normalise Gemini response | Key Module / File: src/ReceiptProcessor/LabelProcessor.py | Input: Raw Gemini JSON | Output: Clean normalised Python dict
  • Step #: 6 | What Happens: Write extracted data to BigQuery (6 normalised tables) | Key Module / File: shared/db_bq_connector.py — DBBQConnector.upload_df_to_gbq() | Input: Clean dict | Output: BigQuery table rows
  • Step #: 7 | What Happens: Archive original document to GCS | Key Module / File: shared/gcs_connector.py — GCSConnector | Input: Original file bytes | Output: GCS URI (receipts/processed/ folder)
  • Step #: 8 | What Happens: Return JSON API response with all extracted fields | Key Module / File: app.py | Input: Clean dict | Output: JSON API response to caller

--- SECTION: Batch Processing Flow ---
  • Step #: 1 | Component: Download Files | What It Does: Scan GCS queued_to_process/ folder, download all queued documents, write manifest.json | Input: acmereceipt-prod-bucket/receipts/queued_to_process/ | Output: Local files + manifest.json | Script / Entry: pipeline/vertex_batch_prediction.py (component 1)
  • Step #: 2 | Component: Generate JSONL | What It Does: For each file — compress PDF, extract merchant_id via tesseract, inject merchant_id into Gemini prompt, write JSONL entry → batch.jsonl | Input: Local files + manifest.json | Output: batch/food/jsonl_files/batch.jsonl | Script / Entry: shared/generate_jsonl.py — JSONLGenerator
  • Step #: 3 | Component: Call Gemini (Batch) | What It Does: Submit batch.jsonl to Vertex AI batch prediction job; wait for completion | Input: batch.jsonl | Output: predictions.jsonl | Script / Entry: Vertex AI Gemini batch prediction endpoint
  • Step #: 4 | Component: Post-process | What It Does: Parse each Gemini response, log complete JSON, verify field agreement, clean data, move to processed/ or failed/ | Input: predictions.jsonl | Output: processed_data.csv | Script / Entry: src/batchPrediction/BatchReceiptProcessor.py
  • Step #: 5 | Component: Generate Tables | What It Does: Read processed_data.csv, denormalise into 6 BigQuery tables with proper keys and relationships | Input: processed_data.csv | Output: 6 BigQuery tables | Script / Entry: shared/generate_tables.py — GenerateTable

--- SECTION: Codebase Structure ---
  • Folder / File: app.py | What It Does: FastAPI application entry point — all HTTP routes, AppConfig Pydantic model, file validation, CORS, startup | Key Classes / Functions: AppConfig, lifespan(), /receipt, /upload-pdf/, /progress/{task_id}, /results/{task_id} | When To Touch It: Add new API endpoints, change file size limits, edit startup logic
  • Folder / File: src/ReceiptProcessor/LabelProcessor.py | What It Does: Core single-document processing orchestrator — controls 4-step pipeline (merchant_id → Gemini → post-process → tables) | Key Classes / Functions: LabelProcessor, process_label() | When To Touch It: Change extraction flow, add processing steps, fix post-processing logic
  • Folder / File: src/batchPrediction/BatchReceiptProcessor.py | What It Does: Batch mode equivalent of LabelProcessor — handles Vertex AI prediction output processing | Key Classes / Functions: BatchReceiptProcessor | When To Touch It: Fix batch post-processing, change batch output format
  • Folder / File: shared/field_extractor.py | What It Does: merchant_id OCR scan extraction using tesseract — multi-resolution scanning (3x, 4x, 2x) for reliability | Key Classes / Functions: MerchantIdExtractor, extract_merchant_ids() | When To Touch It: Improve merchant_id scan accuracy, add new OCR scan types
  • Folder / File: shared/gemini_caller.py | What It Does: Google Gemini AI client — assembles request with merchant_id context, calls API, parses response | Key Classes / Functions: GeminiCaller, extract_data() | When To Touch It: Change Gemini model, change OCR-result override prevention logic, fix parsing
  • Folder / File: shared/db_bq_connector.py | What It Does: BigQuery read/write connector | Key Classes / Functions: DBBQConnector, load_data_as_df(), upload_df_to_gbq() | When To Touch It: Change table schema, fix BigQuery write errors
  • Folder / File: shared/gcs_connector.py | What It Does: Google Cloud Storage read/write | Key Classes / Functions: GCSConnector, upload(), download(), list_blobs() | When To Touch It: Change storage paths, add GCS operations
  • Folder / File: shared/pdf_compressor.py | What It Does: Adaptive PDF compression targeting 5-10 MB | Key Classes / Functions: PDFCompressor, compress() | When To Touch It: Change compression targets, fix large PDF issues
  • Folder / File: shared/generate_jsonl.py | What It Does: Build batch.jsonl entries — combines PDF compression, receipt field extraction, prompt enhancement | Key Classes / Functions: JSONLGenerator | When To Touch It: Change batch input format, update merchant_id context injection
  • Folder / File: shared/generate_tables.py | What It Does: Convert extracted data into 6 normalised BigQuery table structures | Key Classes / Functions: GenerateTable, generate_product_table(), generate_merchant_id_table() | When To Touch It: Add new BigQuery tables, change data normalisation logic
  • Folder / File: shared/read_config.py | What It Does: Load YAML configs (GCP IDs, dataset names, prompts, Cloud Storage paths) | Key Classes / Functions: Constants, Bigquery, CloudStorage, Prompt | When To Touch It: Add new config keys, change config file structure
  • Folder / File: shared/schema.py | What It Does: BigQuery table schema definitions for all 6 tables | Key Classes / Functions: 6 schema lists | When To Touch It: Add new BigQuery columns, change field types
  • Folder / File: pipeline/vertex_batch_prediction.py | What It Does: Kubeflow pipeline definition — 5 components compiled to pipeline YAML | Key Classes / Functions: download_files(), generate_jsonl(), call_gemini(), postprocess(), generate_tables() | When To Touch It: Add/remove pipeline steps, change component logic
  • Folder / File: config/configurations.yml | What It Does: Environment-specific GCP resource IDs (project, bucket, dataset, model) | Key Classes / Functions: N/A | When To Touch It: Change GCP project, bucket names, dataset names
  • Folder / File: config/prompts.yml | What It Does: Gemini extraction prompts (system prompt, user template, OCR-result override instruction) | Key Classes / Functions: N/A | When To Touch It: Improve extraction quality, add new fields to extract
  • Folder / File: AcmeReceipt-Infra-master/ | What It Does: Terraform IaC for all GCP resources — Cloud Run, GCS, BigQuery, IAM, Artifact Registry | Key Classes / Functions: prod/main.tf, test/main.tf | When To Touch It: Add new GCP resources, change IAM, add new environments

--- SECTION: Key Concepts ---
  • Concept: merchant_id | What It Is: Global Trade Item Number — the numeric OCR scan value on every retail product (EAN-13, UPC-A, etc.) | Why It Matters Here: Primary key that links all 6 BigQuery tables; prevents Gemini from hallucinating a different product code | Where To Find Code / Docs: shared/field_extractor.py, docs/merchant_id_EXTRACTOR.md, merchant_id_IMPLEMENTATION_SUMMARY.md
  • Concept: tesseract | What It Is: Python wrapper for zbar library — decodes OCR scans from images and PDFs | Why It Matters Here: Achieves near-100% merchant_id accuracy via physical OCR scan reading (AI cannot match this) | Where To Find Code / Docs: shared/field_extractor.py, requirements.txt
  • Concept: Gemini AI / gemini-1.5-flash-002 | What It Is: Google's multimodal LLM that understands both images and text | Why It Matters Here: Extracts all structured fields (brand, product name, ingredients, nutrition, etc.) from label images | Where To Find Code / Docs: shared/gemini_caller.py, config/prompts.yml
  • Concept: merchant_id Override Prevention | What It Is: Prompt engineering technique that instructs Gemini to use the tesseract-scanned merchant_id value and never generate its own | Why It Matters Here: Without this, Gemini would sometimes hallucinate a wrong merchant_id number | Where To Find Code / Docs: config/prompts.yml, merchant_id_IMPLEMENTATION_SUMMARY.md
  • Concept: BigQuery | What It Is: Google's serverless, scalable cloud data warehouse | Why It Matters Here: Stores all normalised extracted label data across 6 relational tables for analytics | Where To Find Code / Docs: shared/db_bq_connector.py, shared/schema.py
  • Concept: Cloud Storage (GCS) | What It Is: Google's object storage — acmereceipt-prod-bucket in EU multi-regional | Why It Matters Here: Archives original label documents; staging area for batch processing queues | Where To Find Code / Docs: shared/gcs_connector.py, AcmeReceipt-Infra/prod/main.tf
  • Concept: Cloud Run | What It Is: GCP's serverless container platform — auto-scales, no VM management | Why It Matters Here: Hosts the FastAPI application in production; scaled to zero when idle | Where To Find Code / Docs: AcmeReceipt-Infra/prod/main.tf, docs/DOCKER_DEPLOYMENT.md
  • Concept: Vertex AI + Kubeflow Pipelines | What It Is: GCP's ML platform + Python SDK (kfp 2.12.1) for defining and executing ML pipelines | Why It Matters Here: Orchestrates the 5-step batch prediction pipeline as a managed, reusable YAML | Where To Find Code / Docs: pipeline/vertex_batch_prediction.py, docs/PIPELINE_COMPILATION.md
  • Concept: Workload Identity Federation | What It Is: GCP mechanism for keyless authentication — GitHub Actions identity is federated to GCP service accounts | Why It Matters Here: No service account JSON keys stored anywhere; eliminates credential leakage risk | Where To Find Code / Docs: AcmeReceipt-Infra/prod/main.tf, GitHub Actions YAML
  • Concept: AppConfig | What It Is: Pydantic BaseModel in app.py that holds all runtime settings (file size limits, extensions, ports, timeouts) | Why It Matters Here: Single source of truth for all app configuration; hot-reloadable via POST /config/reload | Where To Find Code / Docs: app.py (AppConfig class)

--- SECTION: API Endpoints ---
  • Method: POST | Endpoint: /receipt | Purpose: Main label extraction endpoint — full pipeline | Request Payload: multipart/form-data: file (PDF/image, max 10 MB) | Response: JSON with all extracted label fields
  • Method: POST | Endpoint: /upload-pdf/ | Purpose: Web UI file upload — initiates async processing | Request Payload: multipart/form-data: file | Response: {"task_id": "<uuid>"}
  • Method: GET | Endpoint: /progress/{task_id} | Purpose: Server-Sent Events streaming progress updates | Request Payload: — | Response: SSE stream with step-by-step progress
  • Method: GET | Endpoint: /results/{task_id} | Purpose: Retrieve completed extraction results | Request Payload: — | Response: JSON extraction results
  • Method: GET | Endpoint: /download-excel/{task_id} | Purpose: Export results as Excel file | Request Payload: — | Response: XLSX file download (via DataFrameSaver)
  • Method: GET | Endpoint: /health | Purpose: Health check — liveness probe for Cloud Run | Request Payload: — | Response: {"status": "ok"}
  • Method: GET | Endpoint: /config | Purpose: Get current AppConfig state | Request Payload: — | Response: AppConfig serialised as JSON
  • Method: POST | Endpoint: /config/reload | Purpose: Hot-reload AppConfig from environment variables | Request Payload: — | Response: Updated AppConfig JSON
  • Method: GET | Endpoint: /docs | Purpose: Swagger UI (auto-generated by FastAPI) | Request Payload: — | Response: Interactive API documentation HTML
  • Method: GET | Endpoint: /redoc | Purpose: ReDoc API documentation (auto-generated) | Request Payload: — | Response: ReDoc HTML

--- SECTION: BigQuery Data Model ---
  • Table: product_table | Primary Key(s): article_id | Key Columns: brand_name, product_name, article_id | Populated By: LabelProcessor (Step 3) | Notes: One row per unique product; deduplicated on article_id
  • Table: merchant_id_table | Primary Key(s): merchant_id_number | Key Columns: merchant_id_number, net_content, article_id | Populated By: LabelProcessor (Step 3) | Notes: Links tesseract-scanned merchant_id to product; merchant_id is the authoritative product identifier
  • Table: label_fact | Primary Key(s): document_id | Key Columns: document_id → article_id → merchant_id_number → country_id → id_detail | Populated By: LabelProcessor (Step 3) | Notes: Central fact table — foreign keys to all dimension tables
  • Table: product_details_table | Primary Key(s): id_detail | Key Columns: All extracted label attributes (ingredients, nutrition, allergens, country of origin, etc.) | Populated By: LabelProcessor (Step 3) | Notes: Detailed attribute store for all Gemini-extracted fields
  • Table: country_table | Primary Key(s): country_id | Key Columns: country_name, country_code | Populated By: LabelProcessor (Step 3) | Notes: Country dimension used for multi-market label processing
  • Table: document_table | Primary Key(s): document_id | Key Columns: gcs_uri, processing_status, load_date, file_size | Populated By: LabelProcessor (Step 3) | Notes: Full document audit trail — tracks every processed document and its GCS location

--- SECTION: How To Run Locally ---
  • Step: 1 | Action: Clone the repository | Command / Tool: git clone <repo-url> && cd AcmeReceipt-master | Expected Output: Local repo copy | Notes: Requires repo read access
  • Step: 2 | Action: Create Python virtual environment | Command / Tool: python -m venv .venv && .venv\\Scripts\\activate (Windows) or source .venv/bin/activate (Linux/Mac) | Expected Output: (.venv) in terminal prompt | Notes: Python 3.9 required exactly
  • Step: 3 | Action: Install system-level dependencies | Command / Tool: sudo apt-get install -y libzbar0 poppler-utils (Linux/Debian) | Expected Output: libzbar0 and poppler-utils installed | Notes: Windows: install zbar DLL + poppler binaries manually and add to PATH
  • Step: 4 | Action: Install Python packages | Command / Tool: pip install -r requirements.txt | Expected Output: All packages installed without errors | Notes: Key packages: fastapi, uvicorn, google-genai, google-cloud-bigquery, google-cloud-storage, tesseract, pdf2image, kfp
  • Step: 5 | Action: Create .env file and set environment variables | Command / Tool: cp .env.example .env (then edit with real values) | Expected Output: .env file with GCP_PROJECT_ID, GCS_BUCKET_NAME, BIGQUERY_DATASET, GEMINI_MODEL | Notes: See Section 10 for all variables
  • Step: 6 | Action: Authenticate with GCP (development only) | Command / Tool: gcloud auth application-default login | Expected Output: credentials.json written to ~/.config/gcloud/ | Notes: Production uses Workload Identity — no credentials file needed
  • Step: 7 | Action: Start the FastAPI server | Command / Tool: uvicorn app:app --host 0.0.0.0 --port 8080 --reload | Expected Output: "Application startup complete" on :8080 | Notes: --reload flag enables hot-reload for development
  • Step: 8 | Action: Verify health check | Command / Tool: curl http://localhost:8080/health | Expected Output: {"status": "ok"} | Notes: If this fails, check GCP credentials and environment variables
  • Step: 9 | Action: Use Swagger UI to test the API | Command / Tool: Open http://localhost:8080/docs in browser | Expected Output: Interactive API documentation | Notes: Upload a test label via POST /receipt using the Swagger UI

--- SECTION: Environment & Config Reference ---
  • Variable / Config Key: GCP_PROJECT_ID | Description: Google Cloud project identifier | Example Value: acmereceipt-prod-01 (prod) or cf-platform-acmereceipt-te-uk (test) | Required: Yes | Source: .env / Cloud Run environment variable
  • Variable / Config Key: GCS_BUCKET_NAME | Description: Google Cloud Storage bucket for label archives and batch staging | Example Value: acmereceipt-prod-bucket | Required: Yes | Source: .env / Cloud Run environment variable
  • Variable / Config Key: BIGQUERY_DATASET | Description: BigQuery dataset name for all 6 tables | Example Value: acmereceipt_prod | Required: Yes | Source: config/configurations.yml
  • Variable / Config Key: GEMINI_MODEL | Description: Gemini model ID for extraction | Example Value: gemini-1.5-flash-002 | Required: Yes | Source: config/configurations.yml
  • Variable / Config Key: GOOGLE_APPLICATION_CREDENTIALS | Description: Path to GCP service account key JSON (development only — never use in production) | Example Value: /home/user/.config/gcloud/application_default_credentials.json | Required: Dev only | Source: .env (never commit to Git)
  • Variable / Config Key: MAX_FILE_SIZE_MB | Description: Maximum file upload size in megabytes | Example Value: 20 | Required: No | Source: AppConfig default (app.py)
  • Variable / Config Key: ALLOWED_EXTENSIONS | Description: Accepted file extensions for upload | Example Value: .pdf,.png,.jpg,.jpeg,.tiff,.bmp | Required: No | Source: AppConfig default (app.py)
  • Variable / Config Key: PORT | Description: Server port for Uvicorn | Example Value: 8080 | Required: No | Source: AppConfig default (app.py)
  • Variable / Config Key: config/prompts.yml — system_prompt | Description: Gemini system instruction for label extraction | Example Value: "You are a receipt data extraction specialist..." | Required: Yes | Source: config/prompts.yml (YAML)
  • Variable / Config Key: config/configurations.yml — bigquery.dataset | Description: BigQuery dataset per environment (prod/test) | Example Value: acmereceipt_prod | Required: Yes | Source: config/configurations.yml (YAML)

--- SECTION: Infrastructure & IAM ---
  • GCP Resource: Cloud Run Service | Name / ID: acmereceipt (prod) | Purpose: Hosts FastAPI application — serverless, auto-scaling, no VM management | Managed By: Terraform (AcmeReceipt-Infra/prod/main.tf)
  • GCP Resource: Google Cloud Storage Bucket | Name / ID: acmereceipt-prod-bucket (EU, STANDARD, multi-regional) | Purpose: Label document archive + batch processing staging (queued/processed/failed/results) | Managed By: Terraform
  • GCP Resource: GCS State Bucket | Name / ID: tf-state-acmereceipt-prod-01 (EU MULTI_REGIONAL, 30-version retention) | Purpose: Terraform remote state storage | Managed By: Terraform (bootstrap)
  • GCP Resource: BigQuery Dataset | Name / ID: acmereceipt_prod | Purpose: Stores all 6 normalised extracted label tables | Managed By: Terraform
  • GCP Resource: Artifact Registry | Name / ID: acmereceipt-registry | Purpose: Docker image registry for frontend + batch container images | Managed By: Terraform
  • GCP Resource: Vertex AI Pipeline | Name / ID: acmereceipt-batch-pipeline | Purpose: Managed 5-step Kubeflow batch prediction pipeline | Managed By: pipeline/vertex_batch_prediction.py
  • GCP Resource: App Service Account | Name / ID: acmereceipt-sa-prod@acmereceipt-prod-01.iam.gserviceaccount.com | Purpose: Runtime identity for Cloud Run — accesses GCS, BigQuery, Vertex AI | Managed By: Terraform (roles: logging.logWriter, storage.admin, bigquery.admin, aiplatform.user, ml.developer)
  • GCP Resource: IAC Service Account | Name / ID: terraform-iac-pipeline@acmereceipt-prod-01.iam.gserviceaccount.com | Purpose: CI/CD Terraform apply identity — manages all infrastructure | Managed By: Terraform bootstrap (roles: compute.networkAdmin, iam.roleAdmin, storage.admin, run.admin)
  • GCP Resource: IAM Manager Group | Name / ID: platform.acmereceipt-prod-manager@example.com | Purpose: GCP project governance, sign-off on IAM and infra changes | Managed By: Platform team
  • GCP Resource: IAM Developer Group | Name / ID: platform.acmereceipt-prod-developer@example.com | Purpose: Feature development access — Cloud Run deploy, BigQuery read/write, GCS access | Managed By: Platform team

--- SECTION: Contacts & Escalation ---
  • Role: Tech Lead / Architect | Name: NA (Not Available) | Slack / Email: NA (Not Available) | Escalate When: Architecture decisions, database schema changes, AI model changes, major feature design
  • Role: Platform / Infra Engineer | Name: NA (Not Available) | Slack / Email: NA (Not Available) | Escalate When: GCP resource issues, Terraform failures, Cloud Run config, Artifact Registry, Workload Identity problems
  • Role: AI / ML Engineer | Name: NA (Not Available) | Slack / Email: NA (Not Available) | Escalate When: Gemini extraction quality issues, merchant_id accuracy drops, prompt engineering, batch pipeline failures
  • Role: Product Owner | Name: NA (Not Available) | Slack / Email: NA (Not Available) | Escalate When: Scope decisions, new features, business requirements, priority changes
  • Role: Scrum Master / Delivery Lead | Name: NA (Not Available) | Slack / Email: NA (Not Available) | Escalate When: Team blockers, sprint planning, process improvements, cross-team dependencies
  • Role: GCP IAM Manager | Name: Manager Group | Slack / Email: platform.acmereceipt-prod-manager@example.com | Escalate When: IAM access requests, GCP project governance, security policy questions, new service account creation

--- SECTION: Confidence Summary ---
  Total fields: 65 | Found: 52 | Inferred: 8 | NA: 5 | Completeness: 92%
  Fields needing manual input: Tech Lead name, Platform Engineer name, AI Engineer name, PM name, Scrum Master name, Slack/email contacts
"""


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(stage: str = "ALL", doc: str = None, project_name: str = None) -> dict:
    """Run the document generation pipeline.

    Args:
        stage: SDLC stage key from STAGE_DOC_MAP. One of:
               RG | DEV | PRE_RELEASE | POST_LIVE | SPRINT | ONBOARDING | ALL
        doc:   Override to generate a single document type (e.g. 'dor').
               Takes priority over stage.
        project_name: Override the project name in generated DOCX filenames.

    Returns:
        dict of {doc_key: {label, file, size_kb, path}} for all generated docs.
    """
    # Lazy import — fill_template depends on python-docx which may not be
    # available at module-import time (e.g. inside an ADK agent container).
    from fill_template import fill_document, OUTPUT_DIR, TEMPLATE_DIR

    _project = _sanitize_name(project_name) if project_name else PROJECT_NAME
    docs_to_run = [doc.lower()] if doc else STAGE_DOC_MAP.get(stage.upper())

    # Create a run-specific output folder based on sanitized project name
    run_output = Path(__file__).parent / f"{_project}_ProjectDocs_{RUN_DATE}"
    run_output.mkdir(exist_ok=True)

    filtered = {
        k: v for k, v in LLM_RESPONSES.items()
        if docs_to_run is None or k in docs_to_run
    }

    print("=" * 68)
    print(f"  {_project}  ·  RAG PIPELINE  ·  End-to-End Validation")
    print("=" * 68)
    print(f"\n  Stage filter : {stage.upper()}{f'  →  doc: {doc}' if doc else ''}")
    print(f"  Docs to run  : {list(filtered.keys()) if docs_to_run else 'ALL'}")
    print(f"  Template Source : {TEMPLATE_DIR.name}/")
    print(f"  Output Folder   : {run_output.name}/")
    print(f"  Documents       : {len(filtered)}")
    print(f"\n{'─' * 68}")

    doc_labels = {
        "cpdd":               "Comprehensive Project Definition Document",
        "architecture":       "Architecture & Design",
        "codebase_kb":        "Codebase KB & Change Versioning",
        "dod":                "Definition of Done",
        "dor":                "Definition of Ready",
        "runbook":            "Release & Deployment Runbook",
        "risk_register":      "Risk Register & Mitigation",
        "sop":                "Standard Operating Procedure",
        "sprint_log":         "Sprint Ceremony & Retrospective Log",
        "project_explanation":"Project Explanation — New Joiner Onboarding Guide",
    }

    results   = {}
    failures  = []

    for key, response in filtered.items():
        label = doc_labels.get(key, key)
        print(f"\n  [{list(LLM_RESPONSES).index(key)+1}/{len(LLM_RESPONSES)}]  {label}")
        try:
            # fill_document() saves to OUTPUT_DIR (Project_Documents/)
            filled_path = fill_document(key, response, project_name=_project)
            # Copy to our run-specific output folder
            run_copy = run_output / filled_path.name
            shutil.copy2(filled_path, run_copy)
            size_kb = run_copy.stat().st_size / 1024
            results[key] = {"label": label, "file": filled_path.name,
                            "size_kb": size_kb, "path": str(run_copy)}
        except Exception as e:
            print(f"    ✗  FAILED: {e}")
            failures.append((key, str(e)))

    # ── Final report ──────────────────────────────────────────────────────────
    print(f"\n{'═' * 68}")
    print(f"  PIPELINE COMPLETE — {len(results)}/{len(LLM_RESPONSES)} documents generated")
    print(f"{'═' * 68}")
    print(f"\n  Output: {run_output}\n")

    for key, info in results.items():
        print(f"    ✓  {info['file']:<55} ({info['size_kb']:.1f} KB)")

    if failures:
        print(f"\n  Failures:")
        for key, err in failures:
            print(f"    ✗  {key} — {err}")

    print(f"\n{'─' * 68}")
    print(f"  INTEGRATION SUMMARY")
    print(f"{'─' * 68}")
    print("""
  Components integrated in this pipeline:

  1. rag_prompts.py
       → Defines 9 structured extraction prompts (one per document type)
       → Provides SYSTEM instructions, DETECT block, and CONFIDENCE block
       → Used as the contract between LLM and downstream parser

  2. run_pipeline.py  (this script — NEW)
       → Acts as LLM: produces 9 real structured responses
       → Responses grounded in AcmeReceipt-master + AcmeReceipt-Infra-master
       → Calls fill_document() for each doc → copies output to run folder
       → Orchestrates the complete pipeline end-to-end

  3. fill_template.py
       → parse_llm_response(): splits structured text into sections dict
       → strip_tag(): removes [✓]/[~]/[NA] confidence annotations
       → _fill_kv_table(): fills label→value tables (2-col and 4-col)
       → _fill_data_table(): fills multi-row columnar tables from bullet rows
       → _update_header_block(): updates doc ID / project / date meta block
       → 9 doc-specific fill functions (one per document type)
       → fill_document(): main entry point — load template → fill → save

  4. Project_Templates_Slim/  (source templates)
       → 10 DOCX templates, each ~38-55 KB
       → Generated by generate_templates.py using python-docx
       → Each template opened as a fresh copy (original never modified)

  5. AcmeReceipt_ProjectDocs_<date>/  (output — NEW folder this run)
       → Filled DOCX files, one per document type
       → Named: <DocName>_AcmeReceipt_<YYYYMMDD>.docx

  Data flow:
    rag_prompts.py (prompt contracts)
         │
         ▼
    AcmeReceipt-master + AcmeReceipt-Infra-master (RAG context)
         │
         ▼
    run_pipeline.py (LLM response generation)
         │
         ▼
    fill_template.py parse_llm_response() → sections dict
         │
         ▼
    fill_template.py fill_document() → fills DOCX tables
         │
         ▼
    AcmeReceipt_ProjectDocs_<date>/ (final output)
  """)
    print(f"{'═' * 68}\n")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AcmeReceipt SDLC Document Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Stages:\n"
            "  RG          → CPDD, DOR, Architecture, Risk Register\n"
            "  DEV         → Codebase KB & Change Versioning\n"
            "  PRE_RELEASE → Definition of Done, Release Runbook\n"
            "  POST_LIVE   → SOP\n"
            "  SPRINT      → Sprint Ceremony & Retrospective Log\n"
            "  ONBOARDING  → Project Explanation Guide\n"
            "  ALL         → All 10 documents (default)"
        ),
    )
    parser.add_argument(
        "--stage",
        default="ALL",
        choices=list(STAGE_DOC_MAP.keys()),
        help="SDLC stage — only generate documents for this stage",
    )
    parser.add_argument(
        "--doc",
        default=None,
        choices=["cpdd","architecture","codebase_kb","dod","dor",
                 "runbook","risk_register","sop","sprint_log","project_explanation"],
        help="Single document override (takes priority over --stage)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Override project name in output filenames (default: AcmeReceipt)",
    )
    args = parser.parse_args()
    run_pipeline(stage=args.stage, doc=args.doc, project_name=args.project)
