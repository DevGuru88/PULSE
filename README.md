# PULSE (Project Understanding Lifecycle and SEcurity agent)

> **ℹ️ Personal hackathon project — not affiliated with any employer.** PULSE
> began life as my entry to an internal hackathon and is now published here
> as a personal showcase. The sample data shown throughout — project name
> `AcmeReceipt`, IAM domain `example.com`, GCP project IDs, etc. — is
> **fictional** and exists only so the agent few-shot examples produce
> coherent output. See the
> [Configuration & Customization](#configuration--customization) section for
> how to swap it for your own values before running.

> **⚡ It's just a single command.** Run `bash initial-connector.sh` in GCP Cloud Shell and *everything* — APIs, service accounts, storage buckets, BigQuery tables, secret vaults, Docker images, Cloud Run services, AI agents, RAG knowledge base, security monitoring, Terraform IaC files — is provisioned, built, deployed, and wired together automatically. One command, ~15 minutes, zero manual infrastructure work.

---

## Table of Contents

- [What Is This?](#what-is-this)
- [Who Is This For?](#who-is-this-for)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quick Start — One Command](#quick-start--one-command)
- [Configuration & Customization](#configuration--customization)
- [What Gets Created](#what-gets-created)
- [Interactive Setup Questions](#interactive-setup-questions)
- [Step-by-Step Setup Flow](#step-by-step-setup-flow)
- [Project Structure](#project-structure)
- [SDLC Document Types](#sdlc-document-types)
- [SDLC Stages](#sdlc-stages)
- [Multi-Agent Architecture](#multi-agent-architecture)
- [Dashboard (FastAPI Web UI)](#dashboard-fastapi-web-ui)
- [Security Monitoring (SCC Poller)](#security-monitoring-scc-poller)
- [Document Generation Pipeline](#document-generation-pipeline)
- [RAG Knowledge Base](#rag-knowledge-base)
- [GitHub Integration](#github-integration)
- [Environment Variables Reference](#environment-variables-reference)
- [GCP APIs Enabled](#gcp-apis-enabled)
- [IAM Roles](#iam-roles)
- [API Endpoints](#api-endpoints)
- [Terraform / Infrastructure as Code](#terraform--infrastructure-as-code)
- [Configuration Files](#configuration-files)
- [Uninstall / Teardown](#uninstall--teardown)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## What Is This?

**Lifecycle AI Agent** is an AI-powered platform for **Software Development Lifecycle (SDLC) optimization and automation**, built entirely on Google Cloud Platform and Gemini AI.

It connects to your GCP project and automatically:

- **Generates professional SDLC documents** (architecture docs, risk registers, runbooks, sprint logs, and more) using Gemini AI and RAG-powered knowledge extraction
- **Monitors security** by polling Google Security Command Center for HIGH/CRITICAL findings and generating AI-driven incident reports with root cause analysis and mitigation steps
- **Provides a real-time dashboard** for viewing metrics, incidents, documents, agent execution logs, and a knowledge base search interface
- **Integrates with GitHub** to analyze repositories, pull requests, issues, and code for context-aware document generation
- **Manages a RAG knowledge base** with Vertex AI for semantic search over all project documentation
- **Generates Terraform IaC files** so your infrastructure can be version-controlled and reproducible

**Tech Stack:** Python 3.11 · FastAPI · Google Vertex AI · Gemini 2.5 Pro · Google ADK (Agent Development Kit) · Cloud Run · BigQuery · Cloud Storage · Docker · Terraform

---

## Who Is This For?

PULSE is intended for **engineering and platform teams that build software on Google Cloud** and want to keep their SDLC documentation, security analysis, and project knowledge continuously up to date — without writing or maintaining any of it by hand.

### Typical users

| Role | What you get out of PULSE |
|------|---------------------------|
| **Engineering / Tech Leads** | A single command bootstraps an end-to-end documentation + security platform for a project, with reproducible Terraform IaC and a Cloud Run dashboard. |
| **Developers** | Auto-generated Architecture, Codebase KB, Sprint, and Onboarding docs sourced from your real GitHub repos and code — no manual writing. |
| **Platform / DevOps / SRE** | Continuous Security Command Center polling with AI-generated RCAs, mitigations, and runbook SOPs delivered to a review queue. |
| **Project / Delivery Managers** | A live dashboard with token usage, costs, SDLC stage tracking, sprint logs, and incident reports — with a stage editor to keep the agent in sync. |
| **Compliance / Security teams** | Auditable BigQuery logs of every agent run, every incident, and every generated document, plus IAP-restricted access to the dashboard. |
| **New joiners** | The Knowledge Base chatbot and onboarding doc give new team members a guided way to explore the project from day one. |

### When to use it

- You are starting a new GCP-hosted project and want SDLC documentation generated and indexed automatically.
- You have an existing GCP project and want AI-driven analysis of Security Command Center findings.
- You want a single GCP-native place to ask questions about your code, PRs, and project documents through a RAG-backed agent.
- You want all of the above provisioned reproducibly via Terraform, with no hand-rolled infrastructure.

### When *not* to use it

- You are not running on Google Cloud (the platform is GCP-native — see the FAQ).
- You only need a static documentation site or a simple wiki — PULSE is a multi-agent platform, not a docs hosting tool.
- You cannot grant a service account the IAM roles listed in [IAM Roles](#iam-roles).

---

## Key Features

### 📄 Intelligent Document Generation
- **11 SDLC document types** generated automatically based on project stage
- Professional DOCX output using customizable templates
- AI-powered content extraction from existing repos, code, and documentation
- Stage-aware generation (only creates documents relevant to your current SDLC phase)

### 🔒 Security Incident Analysis
- Automated polling of GCP Security Command Center (HIGH & CRITICAL findings)
- AI-generated Root Cause Analysis (RCA), mitigation steps, and remediation SOPs
- Findings stored in BigQuery for analytics and compliance
- Runs on a configurable schedule (default: every 5 minutes)

### 📊 Real-Time Dashboard
- FastAPI web UI deployed on Cloud Run with IAP access control
- Incident management with AI-generated analysis
- Document management with review/approval workflow
- Agent execution logs with token usage and cost tracking
- Knowledge base semantic search interface

### 🤖 Multi-Agent Architecture
- **RAG Agent** — Retrieves documents from Vertex AI RAG knowledge base
- **GitHub Agent** — Analyzes repositories, PRs, issues via GitHub MCP tools
- **Doc Manager Agent** — Orchestrates document generation, upload, and corpus refresh
- **Root Agent** — Coordinates sub-agents and routes user requests

### 🔗 GitHub Integration
- Read-only access to repositories, code, PRs, issues, and commits via GitHub MCP
- Automatic tech stack and architecture detection
- PR summaries for sprint documentation
- Code analysis for knowledge base enrichment

### 🏗️ Infrastructure as Code
- Auto-generated Terraform files for all provisioned resources
- GCS backend for Terraform state management
- Reproducible infrastructure from day one

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                      USER / EXTERNAL SYSTEMS                        │
│   (Browser)    (GitHub)    (Confluence)    (Jira)    (SCC)           │
└───────┬──────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│              CLOUD RUN — FastAPI Dashboard                           │
│                                                                      │
│   Pages: Dashboard · Incidents · Documents · Knowledge Base          │
│   API:   /api/metrics · /api/incidents · /api/documents · /api/chat  │
│   Auth:  Identity-Aware Proxy (IAP)                                  │
└───────┬──────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│              VERTEX AI — Agent Engine (Google ADK)                    │
│                                                                      │
│   ┌─────────────┐  ┌──────────────┐  ┌────────────────┐             │
│   │  RAG Agent  │  │ GitHub Agent │  │ Doc Manager    │             │
│   │             │  │              │  │ Agent          │             │
│   │ Semantic    │  │ MCP tools:   │  │ Tools:         │             │
│   │ search over │  │ repos, PRs,  │  │ generate_docs, │             │
│   │ knowledge   │  │ issues, code │  │ upload_to_gcs, │             │
│   │ base        │  │              │  │ refresh_corpus │             │
│   └─────────────┘  └──────────────┘  └────────────────┘             │
│                                                                      │
│   ┌──────────────────────────────────────────────────────────┐      │
│   │            Root Agent (Gemini 2.5 Pro)                  │      │
│   │         Routes requests to specialized sub-agents        │      │
│   └──────────────────────────────────────────────────────────┘      │
└───────┬──────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│              DOCUMENT GENERATION PIPELINE                             │
│                                                                      │
│   run_pipeline.py → rag_prompts.py → fill_template.py → DOCX        │
│                                                                      │
│   Stage-Based:  RG → DEV → PRE_RELEASE → POST_LIVE → SPRINT         │
│   Output:       <ProjectName>_ProjectDocs_<YYYYMMDD>/                │
└───────┬──────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│         SECURITY PIPELINE — SCC Poller (Cloud Run Job)               │
│                                                                      │
│   Cloud Scheduler (every 5 min) → fetch_findings.sh → parser-poller  │
│   → Agent analysis → GCS pending-documents/ → Dashboard review       │
└───────┬──────────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────────┐
│                       DATA LAYER (GCP)                               │
│                                                                      │
│   Cloud Storage        BigQuery              Vertex AI RAG           │
│   ├── rag/docs/        ├── agent_exec_log    ├── Indexed DOCX        │
│   ├── pending-docs/    ├── incident_reports  └── Semantic search     │
│   ├── project-docs/    ├── sprint_documents                          │
│   └── logs/            └── deploy_validations                        │
│                                                                      │
│   Secret Manager       Pub/Sub               Cloud Logging           │
│   ├── confluence-token ├── lifecycle-agent-   └── Centralized logs   │
│   └── jira-token           events                                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **GCP Cloud Shell** | The setup script **must** be run inside [GCP Cloud Shell](https://cloud.google.com/shell). It relies on pre-installed tools (`gcloud`, `docker`, `bq`). |
| **GCP Project** | You need a GCP project where you have at minimum the **Editor** role. |
| **Internet Access** | Required for pulling Docker base images during build. |
| **GitHub PAT** *(optional)* | A [GitHub Personal Access Token](https://github.com/settings/personal-access-tokens/new) for repository integration. Recommended scopes: `Contents (read)`, `Pull requests (read)`, `Metadata (read)`. |
| **Confluence URL** *(optional)* | Your Confluence project page URL for documentation integration. |
| **Jira URL** *(optional)* | Your Jira sprint space URL for project tracking integration. |

> **Note:** All GCP APIs, IAM roles, service accounts, and infrastructure are created automatically by the setup script. You do not need to pre-configure anything.

---

## Quick Start — One Command

```bash
# 1. Open GCP Cloud Shell (https://shell.cloud.google.com)

# 2. Clone the repository
git clone https://github.com/solomonpapathoti/pulse.git
cd pulse

# 3. Run the setup — this single command does everything
bash initial-connector.sh
```

The script will:
1. Ask you 6–8 interactive questions (project ID, region, integrations)
2. Show a confirmation summary of what will be created
3. Provision **~30 cloud resources** automatically
4. Deploy the dashboard and AI agents
5. Print your dashboard URL when complete

**Total setup time: ~15–20 minutes.**

---

## Configuration & Customization

PULSE ships configured for a **fictional sample project called `AcmeReceipt`**
— a hypothetical receipt-OCR app for AcmeShop's expense reporting workflow.
The sample exists for one reason only: it gives the multi-agent few-shot
prompts (in `pipeline/run_pipeline.py` and `pipeline/rag_prompts.py`) a
coherent, end-to-end worked example so the document generator produces
realistic output the very first time you run it.

When you adapt PULSE for your own project, you should swap the sample data
out for your real values.

### Sample data you'll want to replace

| Token | Replace with | Where it appears |
|-------|---------------|------------------|
| `AcmeReceipt` / `acmereceipt` | Your project name (CamelCase) and slug (kebab-case) | `pipeline/run_pipeline.py`, `pipeline/rag_prompts.py`, `pipeline/generate_templates.py` |
| `acmereceipt-prod-01`, `acmereceipt-test-01` | Your real GCP project IDs | `pipeline/run_pipeline.py` |
| `platform.acmereceipt-prod-{manager,developer}@example.com` | Your real IAM groups (or remove this section if you don't use IAM groups) | `pipeline/run_pipeline.py`, `pipeline/generate_templates.py` |
| Receipt-OCR domain narrative (`tesseract`, `merchant_id`, etc.) | Your project's actual domain vocabulary | `pipeline/run_pipeline.py`, `pipeline/rag_prompts.py` |

A quick way to find every occurrence:

```bash
# From the repo root
grep -rn 'AcmeReceipt\|acmereceipt\|tesseract\|merchant_id' .
```

### Optional: IAM-group auto-detection

If your organisation issues IAM groups under a central domain (e.g.
`iam.your-company.example`), `initial-connector.sh` can auto-detect the
project's manager group from the GCP IAM policy. Set the `IAM_DOMAIN`
environment variable before running setup:

```bash
IAM_DOMAIN=iam.your-company.example bash initial-connector.sh
```

When `IAM_DOMAIN` is unset (the default), the auto-detection step is
skipped and the connector falls back to deriving the manager group from
the GCP project display name with `example.com` as the domain. This is
purely a convenience feature for organisations with that pattern — it
does **not** affect any of the agent or pipeline functionality.

### DOCX templates are not bundled

The 11 DOCX templates that the SDLC document pipeline fills are **not
shipped** with this repo. The `pipeline/Project_Templates_Slim/` folder
contains a README that lists every expected template plus two minimal
sample templates (`CPDD_Template.docx` and `Architecture_and_Design_Template.docx`)
you can use as a starting point. Drop your own DOCX templates into that
folder before running the pipeline. See
[pipeline/Project_Templates_Slim/README.md](pipeline/Project_Templates_Slim/README.md)
for the full template manifest and naming conventions.

---

## What Gets Created

Running the single setup command provisions the following resources in your GCP project:

### Identity & Access
| Resource | Name | Purpose |
|----------|------|---------|
| Service Account | `lifecycle-agent-sa` | Dedicated SA with 13 IAM roles for all platform operations |
| IAP Binding | — | Identity-Aware Proxy restricts dashboard access to your email |

### Compute & Containers
| Resource | Name | Purpose |
|----------|------|---------|
| Artifact Registry | `lifecycle-agent-repo` | Docker image repository for dashboard |
| Artifact Registry | `scc-poller-repo` | Docker image repository for security poller |
| Cloud Run Service | `lifecycle-agent` | FastAPI dashboard (scales 0→3, 1 vCPU, 1 GiB RAM) |
| Cloud Run Job | `scc-poller-job` | Security findings analysis (serverless, on-demand) |
| Cloud Scheduler | `scc-poller-schedule` | Triggers SCC poller every 5 minutes |

### Storage & Data
| Resource | Name | Purpose |
|----------|------|---------|
| GCS Bucket | `lifecycle-agent-<slug>-data` | Documents, RAG corpus files, logs (versioning enabled) |
| GCS Bucket | `lifecycle-agent-<slug>-tfstate` | Terraform state backend (versioning enabled) |
| BigQuery Dataset | `lifecycle_agent` | 4 tables for agent logs, incidents, sprints, validations |
| Secret Manager | `lifecycle-agent-confluence-token` | Confluence API credentials |
| Secret Manager | `lifecycle-agent-jira-token` | Jira API credentials |

### AI & Messaging
| Resource | Name | Purpose |
|----------|------|---------|
| Vertex AI RAG Corpus | `lifecycle-<slug>-knowledge` | Semantic search over indexed documents |
| Vertex AI Agent Engine | `document-editor` | Multi-agent system for document management |
| Vertex AI Agent Engine | `security-monitor` | Agent for security incident analysis |
| Pub/Sub Topic | `lifecycle-agent-events` | Event routing for future webhook integration |

### Generated Files
| File | Location | Purpose |
|------|----------|---------|
| `main.tf` | `~/lifecycle-agent-infra/` | Terraform IaC for all infrastructure |
| `connector-config.yml` | `~/lifecycle-agent-infra/` | YAML configuration reference |
| `connector.env` | `~/lifecycle-agent-infra/` | Environment variables for reference |
| Setup log | `~/lifecycle-agent-setup.log` | Full log of the setup process |

---

## Interactive Setup Questions

The setup script asks the following questions interactively:

| # | Question | Required? | Default | Example |
|---|----------|-----------|---------|---------|
| 1 | GCP Project ID | Yes | Auto-detected from `gcloud config` | `my-gcp-project-123` |
| 2 | Display name for this connector | Yes | — | `AcmeReceipt`, `My SDLC Agent` |
| 3 | GCP Region | Yes | `europe-west1` | `europe-west1`, `us-central1`, `asia-southeast1` |
| 4 | GitHub Personal Access Token | No | Skip | `github_pat_xxxxx` |
| 5 | GitHub repository names | No | Skip | `org/repo1,org/repo2` |
| 6 | Confluence project page URL | No | Skip | `https://confluence.example.com/display/PROJ` |
| 7 | Jira sprint space URL | No | Skip | `https://jira.example.com/projects/PROJ` |
| 8 | Your email for dashboard access | Yes | Auto-detected from `gcloud` | `you@example.com` |

After answering, you receive a confirmation summary showing every resource that will be created. Press **Enter** to proceed or **Ctrl+C** to abort.

---

## Step-by-Step Setup Flow

The setup script executes in **4 phases** for maximum speed:

### Phase 1 — Sequential Setup (~2 min)
1. **Preflight checks** — Validates `gcloud`, `docker`, `bq` are available and authenticated
2. **Interactive questions** — Collects project configuration
3. **Enable 16 GCP APIs** — Batch-enables all required services
4. **Create service account** — Provisions `lifecycle-agent-sa` with 13 IAM roles

### Phase 2 — Parallel Resource Creation (~2–3 min)
These run simultaneously:
- Create Artifact Registry repositories
- Create GCS buckets (data + Terraform state)
- Create BigQuery dataset with 4 tables
- Create Secret Manager secrets
- Create Pub/Sub topic

### Phase 3 — Parallel Workstreams (~5–8 min)
Three streams running in parallel:
- **Dashboard Pipeline** — Docker build → push → Cloud Run deploy → IAP config
- **RAG Corpus** — Create Vertex AI corpus → import initial documents
- **Security Pipeline** — Build SCC poller → deploy Cloud Run Job → create scheduler

### Phase 4 — Finalization (~2–3 min)
- Deploy AI agents (document-editor, security-monitor) to Vertex AI Agent Engine
- Generate Terraform IaC files
- Print dashboard URL and summary

---

## Project Structure

```
pulse/
│
├── initial-connector.sh          # ⭐ THE setup script — run this one command
├── teardown-connector.sh         # One-command uninstaller — removes every GCP resource created by setup
│
├── Dockerfile                    # Docker image for FastAPI dashboard
│
├── agent_rag_template.py         # Agent template: RAG + GitHub MCP + Doc Manager
├── agent_security_template.py    # Agent template: RAG + GitHub MCP (security-focused)
├── doc_pipeline_tool.py          # ADK-callable tool functions for document generation
├── setup_rag_corpus.py           # Script to create/configure Vertex AI RAG corpus
│
├── webapp/                       # FastAPI dashboard application
│   ├── main.py                   # FastAPI app with all routes and API endpoints
│   ├── requirements.txt          # Python dependencies
│   ├── static/
│   │   ├── css/                  # Stylesheets
│   │   └── js/                   # Client-side JavaScript
│   └── templates/                # Jinja2 HTML templates
│       ├── base.html             # Base layout template
│       ├── index.html            # Landing page
│       ├── dashboard.html        # Main dashboard
│       ├── documents.html        # Document management
│       ├── incidents.html        # Incident viewer
│       ├── knowledge_base.html   # RAG search interface
│       └── feedback.html         # Feedback form
│
├── pipeline/                     # SDLC document generation pipeline
│   ├── run_pipeline.py           # Main pipeline orchestrator
│   ├── rag_prompts.py            # Universal RAG extraction prompts (all 11 doc types)
│   ├── fill_template.py          # Fills DOCX templates with LLM-generated content
│   ├── result_to_docx.py         # Converts LLM output to DOCX format
│   ├── generate_templates.py     # Creates/regenerates DOCX templates
│   └── Project_Templates_Slim/   # 11 DOCX templates
│       ├── CPDD_Template.docx
│       ├── DOR_Template.docx
│       ├── Architecture_and_Design_Template.docx
│       ├── Risk_Register_and_Mitigation_Template.docx
│       ├── Defination_Of_Done_Template.docx
│       ├── Release_and_deployment_runbook_Template.docx
│       ├── SOP_Template.docx
│       ├── Sprint_Retro_Log_Template.docx
│       ├── Project_Explanation_Template.docx
│       ├── Codebase_KB_Change_Versioning_Template.docx
│       └── Security_Report_Template.docx
│
└── scc-poller/                   # Security Command Center polling pipeline
    ├── Dockerfile                # Container image for SCC poller
    ├── entrypoint.sh             # Pipeline orchestration entry point
    ├── fetch_findings.sh         # Fetches SCC findings (HIGH/CRITICAL, last 5 min)
    ├── parser-poller.py          # Parses findings and calls AI agent for analysis
    └── requirements.txt          # Python dependencies
```

---

## SDLC Document Types

The platform generates **11 professional SDLC documents** as formatted DOCX files:

| # | Document | Description |
|---|----------|-------------|
| 1 | **CPDD** (Comprehensive Project Definition Document) | Project scope, objectives, stakeholders, success criteria, constraints |
| 2 | **DOR** (Definition of Requirements) | Functional and non-functional requirements, acceptance criteria, dependencies |
| 3 | **Architecture & Design** | System architecture, component diagrams, technology decisions, integration points |
| 4 | **Risk Register & Mitigation** | Identified risks, probability/impact matrix, mitigation strategies, contingency plans |
| 5 | **Definition of Done (DoD)** | Completion criteria checklist for features, sprints, and releases |
| 6 | **Release & Deployment Runbook** | Step-by-step deployment procedures, rollback plans, verification steps |
| 7 | **SOP** (Standard Operating Procedure) | Operational procedures for monitoring, incident response, and maintenance |
| 8 | **Sprint Ceremony & Retrospective Log** | Sprint planning, review, and retrospective summaries with action items |
| 9 | **Project Explanation / Onboarding Guide** | New team member onboarding, project overview, getting started guide |
| 10 | **Codebase KB & Change Versioning** | Codebase structure documentation, change log, versioning conventions |
| 11 | **Security Report** | Security posture assessment, vulnerability summary, compliance status |

Each document is generated using:
- **Customizable DOCX templates** in `pipeline/Project_Templates_Slim/`
- **AI-powered content extraction** via Gemini 2.5 Pro with RAG context
- **Universal prompts** in `pipeline/rag_prompts.py` that adapt to any SDLC methodology

---

## SDLC Stages

Documents are generated based on the project's current SDLC stage. Each stage produces a specific subset of documents:

| Stage | Code | Documents Generated |
|-------|------|---------------------|
| **Requirements Gathering** | `RG` | CPDD, DOR, Architecture & Design, Risk Register |
| **Development** | `DEV` | Codebase KB & Change Versioning |
| **Pre-Release** | `PRE_RELEASE` | Definition of Done, Release & Deployment Runbook |
| **Post-Live** | `POST_LIVE` | SOP (Standard Operating Procedure) |
| **Sprint** | `SPRINT` | Sprint Ceremony & Retrospective Log |
| **Onboarding** | `ONBOARDING` | Project Explanation / Onboarding Guide |
| **All** | `ALL` | All 11 documents |

The current stage is stored in `stage.json` on GCS and can be detected automatically or set manually through the agent or dashboard.

> **Note:** The Pulse dashboard exposes the SDLC stage card under *Project Phase*, which reads from and writes to `stage.json` via `GET`/`POST /api/project-stage`. This file is the system-of-record that the Knowledge Base chatbot (the `doc_manager_agent`) reads via `detect_project_stage()` — set the stage on the dashboard and the agent will use it without prompting you.

---

## Multi-Agent Architecture

The platform uses Google's **Agent Development Kit (ADK)** to orchestrate multiple specialized agents:

### Agent Templates

#### `agent_rag_template.py` — Document Editor Agent
Deployed as the `document-editor` agent with 4 sub-agents:

| Agent | Role | Tools |
|-------|------|-------|
| **Root Agent** | Coordinator — routes requests to sub-agents | — |
| **RAG Agent** | Semantic search over knowledge base | `VertexAiRagRetrieval` (top-10 results) |
| **GitHub Agent** | Repository analysis | GitHub MCP Toolset (repos, PRs, issues, code) |
| **Doc Manager Agent** | Document lifecycle management | `detect_project_stage`, `set_project_stage`, `generate_documents`, `upload_docs_to_gcs` (uploads to pending-review queue), `check_document_staleness` |

#### `agent_security_template.py` — Security Monitor Agent
Deployed as the `security-monitor` agent with 3 sub-agents:

| Agent | Role | Tools |
|-------|------|-------|
| **Root Agent** | Coordinator (security-focused instructions) | — |
| **RAG Agent** | Knowledge base retrieval | `VertexAiRagRetrieval` |
| **GitHub Agent** | Repository analysis | GitHub MCP Toolset |

### Doc Pipeline Tool Functions (`doc_pipeline_tool.py`)

These functions are callable by the Doc Manager Agent:

| Function | Purpose |
|----------|---------|
| `detect_project_stage()` | Reads `stage.json` from GCS to determine current SDLC phase |
| `set_project_stage(stage, sprint)` | Updates `stage.json` on GCS |
| `generate_documents(stage, doc, project_name)` | Runs the document generation pipeline for the given stage |
| `upload_docs_to_gcs(output_dir, gcs_bucket, gcs_prefix)` | Uploads generated DOCX files to the GCS **pending-review** folder (default: `pending-documents/`, overridable via `PENDING_DOCS_FOLDER`). Documents become searchable only after a reviewer approves them on the dashboard. |
| `refresh_rag_corpus(gcs_bucket, gcs_prefix, corpus_uri)` | Re-imports GCS documents into Vertex AI RAG corpus. Called by the dashboard after a reviewer approves a pending document; **not** exposed to the agent. |
| `check_document_staleness(gcs_bucket, gcs_prefix, max_age_days)` | Flags documents older than `max_age_days` (default: 30) |

---

## Dashboard (FastAPI Web UI)

The dashboard is a **FastAPI application** deployed on Cloud Run with IAP access control.

### Pages

| Page | URL | Description |
|------|-----|-------------|
| Landing | `/` | Welcome page with setup status |
| Dashboard | `/dashboard` | Main metrics overview — token usage, costs, agent runs, **Project Phase tracker** (visual SDLC progress), and **SDLC Stage editor** (writes `stage.json` so the Knowledge Base chatbot trusts the stored stage instead of asking) |
| Incidents | `/incidents` | Security incident viewer with AI-generated analysis |
| Documents | `/documents` | Document management — view, review, approve generated docs |
| Knowledge Base | `/knowledge-base` | Semantic search interface for the RAG corpus |
| Feedback | `/feedback` | User feedback form for agent responses |

### Technology
- **Backend:** FastAPI + Uvicorn
- **Templates:** Jinja2
- **Styling:** Custom CSS
- **Container:** Python 3.11 slim, exposed on port 8080
- **Health Check:** `GET /api/metrics` every 30 seconds
- **Access Control:** Google Identity-Aware Proxy (only authorized users)

---

## Security Monitoring (SCC Poller)

The security pipeline continuously monitors your GCP project for security findings:

### How It Works

1. **Cloud Scheduler** triggers the `scc-poller-job` Cloud Run Job on a schedule (default: every 5 minutes)
2. **`fetch_findings.sh`** queries GCP Security Command Center for `ACTIVE` findings with `HIGH` or `CRITICAL` severity from the last 5-minute window
3. **`parser-poller.py`** parses the findings and sends each one to the security-monitor AI agent
4. The agent generates:
   - Root Cause Analysis (RCA)
   - Mitigation steps
   - Remediation SOP
   - Knowledge base documentation
5. Responses are uploaded to `gs://<bucket>/pending-documents/` for review through the dashboard

### Container Stack
- **Base:** Python 3.11 slim
- **Includes:** `gcloud` CLI, `jq`, `curl`, `bash`
- **Entry Point:** `entrypoint.sh` → `fetch_findings.sh` → `parser-poller.py`

---

## Document Generation Pipeline

The `pipeline/` directory contains the complete document generation system:

### Flow

```
User/Agent Request
    ↓
detect_project_stage()          ← reads stage.json from GCS
    ↓
run_pipeline(stage="DEV")       ← determines which documents to generate
    ↓
STAGE_DOC_MAP[stage]            ← maps stage to document types
    ↓
For each document type:
  1. Load template from Project_Templates_Slim/
  2. Generate content via Gemini AI + RAG context
  3. Fill template using fill_template.py
  4. Save: <Project>_ProjectDocs_<YYYYMMDD>/<doc_name>_Filled.docx
    ↓
upload_docs_to_gcs()            ← uploads DOCX files to the GCS pending-review folder
    ↓
[Human reviewer approves on /documents page]
    ↓
refresh_rag_corpus()            ← (triggered by the dashboard on approval) re-indexes documents in Vertex AI RAG
```

### Key Components

| File | Purpose |
|------|---------|
| `run_pipeline.py` | Main orchestrator — stage detection, document routing, output management |
| `rag_prompts.py` | Universal prompts for all 11 document types — adaptive extraction rules, terminology mapping, confidence tagging |
| `fill_template.py` | Parses structured LLM responses and fills DOCX templates while maintaining formatting |
| `result_to_docx.py` | Converts raw LLM output to structured DOCX format |
| `generate_templates.py` | Creates/regenerates the DOCX templates from scratch |

### Standalone Usage

```bash
# Generate documents for a specific stage
python pipeline/run_pipeline.py --stage DEV --project "MyProject"

# Generate a single document type
python pipeline/run_pipeline.py --doc cpdd

# Demo mode (auto-generates with sample data)
python pipeline/run_pipeline.py --demo
```

---

## RAG Knowledge Base

The platform maintains a **Vertex AI RAG corpus** for semantic search over project documentation.

### How It Works
- Documents (DOCX, PDF) are uploaded to `gs://<bucket>/rag/docs/`
- The `setup_rag_corpus.py` script creates a Vertex AI RAG corpus and imports documents
- Documents are chunked (512 tokens default) and embedded using Vertex AI's built-in embedding model
- The RAG Agent performs top-10 semantic search with similarity threshold filtering

### Corpus Management

```bash
# Create or update RAG corpus (called automatically during setup)
python setup_rag_corpus.py \
  --project-id YOUR_PROJECT \
  --region europe-west1 \
  --corpus-name lifecycle-myproject-knowledge \
  --gcs-path gs://my-bucket/rag/docs/
```

The corpus is automatically refreshed when:
- New documents are generated via the pipeline
- Documents are uploaded through the dashboard
- The `refresh_rag_corpus()` tool function is called by an agent

---

## GitHub Integration

### Setup
Provide a GitHub Personal Access Token (PAT) during the interactive setup. The PAT enables the GitHub Agent to access your repositories.

**Recommended PAT scopes:**
- ✅ `Contents` — Read repository files and code
- ✅ `Pull requests` — Read PR details, diffs, reviews
- ✅ `Metadata` — Read repository metadata
- ✅ `Dependabot alerts` — Read vulnerability information

### Capabilities
The GitHub Agent uses **MCP (Model Context Protocol)** tools to:
- List and search repositories
- Fetch file contents and directory structures
- Read pull requests (title, description, author, status, diff)
- Read issues (title, labels, assignees, linked PRs)
- List commits with details
- Analyze repository metadata (language, topics, description)

### Use Cases
- **Sprint Logs:** Fetch merged PRs to generate sprint documentation
- **Architecture Docs:** Analyze codebase structure and dependencies
- **Onboarding Guides:** Extract project context from README, docs, code
- **Security Reports:** Cross-reference code with vulnerability findings

> **Note:** GitHub integration is read-only (`X-MCP-Readonly: true`). No write operations are performed on your repositories.

---

## Environment Variables Reference

### Core Configuration (set automatically by setup script)

| Variable | Description | Example |
|----------|-------------|---------|
| `GCP_PROJECT_ID` | Google Cloud Project ID | `my-project-123` |
| `GCP_REGION` | GCP region for all resources | `europe-west1` |
| `GOOGLE_CLOUD_PROJECT` | Alias for `GCP_PROJECT_ID` (used by Google SDKs) | `my-project-123` |
| `GOOGLE_CLOUD_LOCATION` | Alias for `GCP_REGION` (used by Google SDKs) | `europe-west1` |
| `CONNECTOR_NAME` | Display name for this connector | `AcmeReceipt` |
| `CONNECTOR_SLUG` | URL-safe slug derived from display name | `acmereceipt` |
| `ENVIRONMENT` | Deployment environment | `production` |

### Integration Variables (optional)

| Variable | Description | Example |
|----------|-------------|---------|
| `GITHUB_REPOS` | Comma-separated GitHub repositories | `org/repo1,org/repo2` |
| `GITHUB_PAT` | GitHub Personal Access Token | `github_pat_xxxxx` |
| `CONFLUENCE_URL` | Confluence project page URL | `https://confluence.example.com/display/PROJ` |
| `JIRA_URL` | Jira sprint space URL | `https://jira.example.com/projects/PROJ` |

### Infrastructure Variables (set automatically)

| Variable | Description | Example |
|----------|-------------|---------|
| `GCS_DATA_BUCKET` | GCS bucket for documents and data | `lifecycle-agent-myproject-data` |
| `CORPUS_RESOURCE_NAME` | Vertex AI RAG corpus resource path | `projects/.../ragCorpora/...` |
| `AGENT_ENGINE_ID` | Vertex AI Agent Engine ID | `1234567890` |

### Secrets (stored in Secret Manager)

| Secret Name | Purpose |
|-------------|---------|
| `lifecycle-agent-confluence-token` | Confluence API credentials |
| `lifecycle-agent-jira-token` | Jira API credentials |

---

## GCP APIs Enabled

The setup script automatically enables 16 GCP APIs:

| API | Service | Purpose |
|-----|---------|---------|
| `run.googleapis.com` | Cloud Run | Dashboard + SCC poller deployment |
| `aiplatform.googleapis.com` | Vertex AI | Agents, Gemini models, RAG corpus |
| `bigquery.googleapis.com` | BigQuery | Agent logs, incidents, sprints, validations |
| `storage.googleapis.com` | Cloud Storage | Documents, RAG corpus files, Terraform state |
| `secretmanager.googleapis.com` | Secret Manager | Confluence/Jira tokens |
| `logging.googleapis.com` | Cloud Logging | Centralized application logs |
| `monitoring.googleapis.com` | Cloud Monitoring | Metrics and alert data |
| `cloudbuild.googleapis.com` | Cloud Build | Docker image builds |
| `artifactregistry.googleapis.com` | Artifact Registry | Docker image storage |
| `iap.googleapis.com` | Identity-Aware Proxy | Dashboard access control |
| `pubsub.googleapis.com` | Pub/Sub | Event routing |
| `cloudscheduler.googleapis.com` | Cloud Scheduler | SCC poller scheduling |
| `cloudresourcemanager.googleapis.com` | Resource Manager | IAM role management |
| `connectors.googleapis.com` | Connectors | External system connectors |
| `discoveryengine.googleapis.com` | Discovery Engine | Enhanced search capabilities |
| `securitycommandcenter.googleapis.com` | Security Command Center | Security findings feed |

---

## IAM Roles

The `lifecycle-agent-sa` service account is granted the following roles:

| Role | Purpose |
|------|---------|
| `roles/aiplatform.user` | Access Vertex AI agents, models, RAG |
| `roles/bigquery.dataEditor` | Read/write BigQuery tables |
| `roles/bigquery.jobUser` | Run BigQuery queries |
| `roles/storage.objectAdmin` | Manage GCS objects |
| `roles/logging.viewer` | Read Cloud Logging |
| `roles/monitoring.viewer` | Read Cloud Monitoring metrics |
| `roles/secretmanager.secretAccessor` | Read secret values |
| `roles/secretmanager.viewer` | List secrets |
| `roles/pubsub.publisher` | Publish to Pub/Sub topics |
| `roles/pubsub.subscriber` | Subscribe to Pub/Sub topics |
| `roles/run.invoker` | Invoke Cloud Run services |
| `roles/connectors.admin` | Manage connectors |
| `roles/securitycenter.findingsViewer` | Read SCC findings |

---

## API Endpoints

The FastAPI dashboard exposes the following endpoints:

### Pages (HTML)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Landing page |
| `GET` | `/dashboard` | Main dashboard with metrics |
| `GET` | `/documents` | Document management interface |
| `GET` | `/incidents` | Incident viewer |
| `GET` | `/knowledge-base` | RAG knowledge base search |
| `GET` | `/feedback` | Feedback submission form |

### API (JSON)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/setup` | Initial connector setup (persists configuration captured by the dashboard) |
| `GET` | `/api/metrics` | Usage metrics (tokens, costs, agent runs); also used as the Cloud Run liveness probe |
| `GET` | `/api/runs` | Agent execution history |
| `GET` | `/api/incidents` | Fetch incidents from Monitoring + SCC |
| `POST` | `/api/incidents/refresh` | Manually refresh the incident list (falls back to demo data when GCP is unavailable) |
| `POST` | `/api/incidents/trigger` | Trigger the security-monitor agent to analyse a specific incident |
| `GET` | `/api/project-stage` | Read the current SDLC stage from `gs://<bucket>/stage.json` (system-of-record for the doc_manager_agent) |
| `POST` | `/api/project-stage` | Persist the SDLC stage (and optional sprint number) to `stage.json` from the dashboard editor |
| `GET` | `/api/documents` | List generated documents |
| `POST` | `/api/documents/refresh` | Force-regenerate documents |
| `GET` | `/api/documents/{doc_id}` | Get a specific document's metadata / preview |
| `GET` | `/api/documents/{doc_id}/download` | Download the underlying DOCX file |
| `POST` | `/api/documents/{doc_id}/review` | Submit review / approval feedback on a document |
| `POST` | `/api/chat` | Chat with AI agents (streaming) |
| `GET` | `/api/chat/history` | Retrieve the current session's chat history |
| `DELETE` | `/api/chat/history` | Clear the current session's chat history |
| `GET` | `/api/feedback` | List submitted feedback entries |
| `POST` | `/api/feedback` | Submit feedback on an agent response |

---

## Terraform / Infrastructure as Code

After setup completes, Terraform files are generated in `~/lifecycle-agent-infra/`:

### `main.tf`
Complete Terraform configuration including:
- **Provider:** `hashicorp/google ~> 5.0`
- **Backend:** GCS (for remote state management)
- **Resources:** Service account, IAM roles, Artifact Registry, GCS buckets, BigQuery dataset, Secret Manager, Pub/Sub, Cloud Run service + IAP
- **Outputs:** Dashboard URL, service account email, data bucket name, BigQuery dataset ID

### `connector-config.yml`
YAML configuration reference containing:
- Connector metadata (name, slug, creation timestamp)
- GCP project and region configuration
- Integration settings (GitHub, Confluence, Jira)
- Infrastructure resource names and URLs
- Agent configuration (model, temperature, RAG settings)

### Usage

```bash
cd ~/lifecycle-agent-infra/

# Initialize Terraform
terraform init

# Preview changes
terraform plan

# Apply changes (for ongoing infrastructure management)
terraform apply
```

---

## Configuration Files

### BigQuery Tables

The `lifecycle_agent` dataset contains 4 tables:

#### `agent_execution_log`
Tracks every agent invocation with:
- `execution_id`, `agent_type`, `trigger_source`, `connector_name`
- `event_payload`, `gemini_request`, `gemini_response`, `tools_called`
- `execution_time_ms`, `token_count_input`, `token_count_output`, `cost_usd`
- `status`, `error_message`, `created_at`

#### `incident_reports`
Stores security incidents and analysis:
- `incident_id`, `alert_name`, `severity`, `root_cause_analysis`
- `mitigation_steps`, `affected_services`, `confidence_score`
- `jira_ticket_id`, `github_issue_url`, `status`, `resolved_at`

#### `sprint_documents`
Captures sprint ceremony outputs:
- `sprint_id`, `sprint_label`, `start_date`, `end_date`
- `prs_merged`, `issues_closed`, `features_delivered`, `bugs_fixed`
- `blockers`, `dod_checklist`, `document_markdown`

#### `deployment_validations`
Records deployment readiness checks:
- `validation_id`, `pr_number`, `repository`
- `ci_checks_passed`, `tests_passed`, `pr_approved`, `docs_updated`
- `infra_validated`, `overall_ready`, `checklist_json`, `warnings`

### GCS Bucket Structure

```
lifecycle-agent-<slug>-data/
├── rag/docs/              # RAG-indexed documents (DOCX, PDF)
├── pending-documents/     # SCC findings awaiting review
├── project-docs/          # Generated project documentation
├── logs/                  # Application logs
└── stage.json             # Current SDLC stage configuration
```

---

## Uninstall / Teardown

PULSE ships with a one-command uninstall script that removes **every** GCP resource created by `initial-connector.sh`. It is the symmetrical counterpart of the setup script.

```bash
cd pulse
bash teardown-connector.sh
```

### What it does (in strict reverse-dependency order)

1. Reads configuration from `connector.env` (or asks for the project details if the file is missing)
2. Displays a detailed warning of everything that will be deleted
3. Requires you to type **`I Agree`** before proceeding (no accidental deletions)
4. Deletes Cloud Scheduler job → Cloud Run Job (SCC poller) → Cloud Run Service (dashboard)
5. Deletes the Vertex AI Agent Engines (`document-editor`, `security-monitor`)
6. Deletes the Vertex AI RAG corpus
7. Deletes Pub/Sub topic, Secret Manager secrets, BigQuery dataset (cascade)
8. Deletes both GCS buckets (data + Terraform state)
9. Deletes Artifact Registry repositories (with all images)
10. Removes IAM role bindings and deletes the `lifecycle-agent-sa` service account
11. Optionally disables the GCP APIs that were enabled during setup

> **Warning:** Teardown is destructive and irreversible. Generated documents, indexed RAG content, BigQuery logs, and Terraform state stored in the GCS buckets will be permanently deleted. Back up anything you want to keep before running it.

---

## Troubleshooting

### Setup script fails with permission errors
Ensure you have at minimum the **Editor** role on the GCP project. The script needs to enable APIs, create service accounts, and assign IAM roles.

### Docker build fails in Cloud Shell
Cloud Shell has limited disk space. Run `docker system prune -af` before retrying the setup.

### Dashboard shows "403 Forbidden"
IAP is configured to allow only your email. Verify the correct email was detected during setup. You can update IAP access in the [GCP Console](https://console.cloud.google.com/security/iap).

### Agent Engine deployment fails
Vertex AI Agent Engine requires the `aiplatform.googleapis.com` API and sufficient quota. Check that the API is enabled and you have quota for Vertex AI resources in your region.

### SCC Poller finds no findings
The poller only looks at the last 5-minute window. If there are no recent HIGH/CRITICAL findings, it will report no results. This is expected behavior.

### Documents not appearing in RAG search
After generating documents, the agent uploads them to the **pending-review** folder (`pending-documents/`) — they will only appear in the RAG knowledge base after a reviewer approves them on the dashboard's `/documents` page. On approval, the dashboard automatically promotes the file to `rag/docs/` and calls `refresh_rag_corpus()`. RAG indexing may then take a few minutes.

### GitHub integration not working
Verify that your GitHub PAT has not expired and has the required scopes (Contents, Pull requests, Metadata). The PAT can be updated by redeploying the Cloud Run service with the new token.

### Re-running the setup script
The setup script is **idempotent** — it checks if each resource already exists before creating it. Re-running safely skips existing resources and only creates missing ones.

---

## FAQ

**Q: What GCP costs should I expect?**
- **Idle (no requests):** ~$0.01/day (Cloud Run scales to zero)
- **Active usage:** ~$1–2/day depending on agent invocations and Gemini API calls
- Main cost drivers: Vertex AI / Gemini API calls, Cloud Run compute, BigQuery storage

**Q: Can I use this with a non-GCP project?**
No. This platform is designed specifically for Google Cloud Platform and depends on multiple GCP services.

**Q: Can I add more GitHub repositories after setup?**
Yes. Update the `GITHUB_REPOS` environment variable on the Cloud Run service and redeploy, or re-run the setup script.

**Q: What Gemini model is used?**
The agents use **Gemini 2.5 Pro** (`gemini-2.5-pro`) for all AI-powered operations.

**Q: Is the GitHub integration read-only?**
Yes. All GitHub MCP tools are configured with `X-MCP-Readonly: true`. No write operations are performed on your repositories.

**Q: Can I customize the document templates?**
Yes. Edit the DOCX templates in `pipeline/Project_Templates_Slim/` and rebuild/redeploy the dashboard container.

**Q: How do I add Confluence/Jira tokens after setup?**
Update the secrets in [Secret Manager](https://console.cloud.google.com/security/secret-manager) — replace the `REPLACE_ME` placeholder values with your actual API tokens.

**Q: Can I deploy to a region other than europe-west1?**
Yes. The setup script offers `europe-west1`, `us-central1`, and `asia-southeast1` as region options during the interactive setup.

**Q: How do I access the dashboard?**
After setup, the script prints the Cloud Run service URL. Access it in your browser — IAP will prompt you to sign in with the email you specified during setup.

**Q: How do I monitor agent performance?**
The dashboard shows agent execution metrics including token usage, execution time, costs, and tool calls. Historical data is stored in the `agent_execution_log` BigQuery table.

***


### Made with ❤️ by [Solomon Leo](https://github.com/solomonpapathoti)
