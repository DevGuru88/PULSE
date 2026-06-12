"""
rag_prompts.py  —  Universal RAG Document Extraction Prompts
=============================================================
Works with ANY:
  SDLC        : Scrum · Kanban · SAFe · Waterfall · Shape Up · DevOps · XP
  Project type: Web App · Mobile · Microservices · Monolith · ML/AI · Data Pipeline
                Embedded · SaaS · API-only · Internal Tool
  Ticket tool : Jira · GitHub Issues · Linear · Azure DevOps · Trello · Notion · Monday
  Repo host   : GitHub · GitLab · Bitbucket · Azure Repos · Gitea
  CI/CD       : GitHub Actions · GitLab CI · Jenkins · Azure DevOps · CircleCI · TeamCity
  Docs        : Confluence · Notion · Readme.io · GitHub Wiki · SharePoint

Usage:
    from rag_prompts import SYSTEM, PROMPTS
    full_prompt = SYSTEM + "\\n\\n" + PROMPTS["architecture"]
    response = llm.query(full_prompt, context=rag_chunks)
"""

# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM INSTRUCTION  —  Prepend to EVERY prompt
# ══════════════════════════════════════════════════════════════════════════════
SYSTEM = """
You are a senior technical documentation specialist with expertise across all
software development methodologies and project types.

You have been given RAG context chunks from one or more of the following sources:
  SOURCE TYPES (use whatever is present — do not require all):
  • Version Control  : Git commits, branches, PRs, tags, CHANGELOG, README, ADR files,
                       code comments (TODO/FIXME/HACK), CI/CD YAML, Dockerfile, IaC files
  • Ticket System    : Jira / GitHub Issues / Linear / Azure DevOps / Trello / Notion /
                       Monday — any combination of epics, stories, tasks, bugs, sprints,
                       labels, comments, priorities, assignees, milestones, releases
  • Documentation    : Confluence / Notion / Wiki pages / Readme.io / SharePoint / PDFs
  • Monitoring/Infra : Alert configs, dashboard exports, Terraform, Kubernetes manifests,
                       environment configuration files

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXTRACTION RULES  (follow strictly)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
R1. ONLY use information present in the provided context. Never invent or hallucinate.

R2. MISSING DATA: For any field with no information found, write exactly:
      NA (Not Available)
    Do not leave fields blank.

R3. CONFIDENCE TAG: Append one tag after every extracted value:
      [✓ found]    — directly stated in context
      [~ inferred] — reasonably deduced (e.g. language from file extensions, SDLC from board type)
      [NA]         — not found in context

R4. CONFLICT RESOLUTION: If two sources give different values for the same field:
      Priority: Official docs / release ticket > Git tag / CHANGELOG > commit message > README
      Write the highest-priority value and append: [⚠ conflict: also "<other value>" in <source>]

R5. ADAPTIVE EXTRACTION:
      Step 1 — DETECT the project context FIRST (SDLC, project type, tools) using the DETECT block
      Step 2 — Extract standard sections that apply to ALL projects
      Step 3 — Extract CONDITIONAL sections only if they apply to the detected context

R6. SDLC TERMINOLOGY MAPPING (extract equivalent concepts regardless of name used):
      "Sprint / Iteration / Cycle / Phase / Milestone"  → treat as time-boxed work unit
      "Epic / Feature / Theme / Module"                → treat as large work item
      "Story / Task / Card / Work Item / Ticket / Issue" → treat as atomic work unit
      "PO / PM / Product Manager / Feature Owner"      → treat as requirement owner
      "Scrum Master / Agile Coach / Delivery Lead"     → treat as process facilitator

R7. COMPLETENESS SUMMARY: End every response with a Confidence Summary section as instructed
    in each prompt — this is mandatory, not optional.
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED DETECT BLOCK  (inserted at the top of every prompt)
# ══════════════════════════════════════════════════════════════════════════════
_DETECT = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — DETECT PROJECT CONTEXT  (do this FIRST before any extraction)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scan the context and identify:

  SDLC Methodology:
    Options → Scrum · Kanban · SAFe · Waterfall · Shape Up · DevOps/Continuous · XP · Hybrid
    Signal  → Sprint boards = Scrum | Continuous flow / no sprints = Kanban | Program Increments = SAFe
              Phases/Gates (Requirements→Design→Dev→Test→Deploy) = Waterfall | Cycles/Bets = Shape Up

  Project Type:
    Options → Web App · Mobile (iOS/Android) · Microservices · Monolithic · ML/AI · Data Pipeline
              Embedded/IoT · SaaS Platform · API-Only · Internal Tool · Hybrid
    Signal  → Dockerfile+API routes = Web/Microservice | .ipynb/model files = ML/AI
              DAG/pipeline configs = Data Pipeline | firmware/RTOS = Embedded

  Primary Ticket Tool:   Jira · GitHub Issues · Linear · Azure DevOps · Trello · Notion · Monday · Unknown
  Primary Repo Host:     GitHub · GitLab · Bitbucket · Azure Repos · Other
  Primary CI/CD:         GitHub Actions · GitLab CI · Jenkins · Azure DevOps · CircleCI · TeamCity · Other
  Primary Doc System:    Confluence · Notion · GitHub Wiki · Readme.io · SharePoint · None found

--- SECTION: Project Context (Detected) ---
  SDLC Methodology:   __
  Project Type:       __
  Ticket Tool:        __
  Repo Host:          __
  CI/CD Platform:     __
  Doc System:         __
  Detection Basis:    [brief evidence — e.g. "sprint board found in Jira, Dockerfile present, GitHub Actions YAML"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — EXTRACT SECTIONS BELOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""".strip()

_CONFIDENCE = """
--- SECTION: Confidence Summary ---
  Total fields in this document:   __
  Fully found   [✓]:               __
  Inferred      [~]:               __
  Not available [NA]:              __  → List them: __
  Completeness score:              __% ( (found + inferred) / total × 100 )
  Fields needing manual input:     __
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  1. ARCHITECTURE & DESIGN  (arc42 · C4 · any)
# ══════════════════════════════════════════════════════════════════════════════
ARCHITECTURE = f"""
TASK: Extract all information needed to fill the Architecture & Design Document.

SOURCE PRIORITY (scan all available, prioritise in this order):
  1. Dedicated arch docs (arc42, C4 model, ADR folder, /docs, /architecture)
  2. README — system overview, architecture section
  3. Code structure (src/, services/, modules/ layout reveals component design)
  4. IaC / Dockerfile / K8s manifests (reveal infra topology)
  5. CI/CD YAML (reveals pipeline and deployment targets)
  6. Ticket system (architecture epics, NFR tickets, design decisions)

{_DETECT}

--- SECTION: Purpose & Scope ---
  [2–3 factual sentences: what business/technical problem does this system solve,
   who uses it, and what are its hard boundaries?]

--- SECTION: System Context — Actors & Integrations ---
  [Every user type and external system that interacts with this system]
  • Actor/System: __ | Type: Human User / External API / Internal Service / DB / Queue / 3rd Party
    Interaction: __ | Protocol: REST / GraphQL / gRPC / Event / File / Other

--- SECTION: Technology Stack ---
  [Fill all rows; if a layer does not exist write NA]
  Layer            | Technology & Version      | Justification (from docs/code)
  Frontend         | __ ver __                 | __
  Backend / API    | __ ver __                 | __
  Database (OLTP)  | __ ver __                 | __
  Database (OLAP)  | __ ver __                 | __
  Cache            | __ ver __                 | __
  Message Queue    | __ ver __                 | __
  Auth / IAM       | __ ver __                 | __
  Search           | __ ver __                 | __
  Infra / Cloud    | __ ver __                 | __
  Container Orch.  | __ ver __                 | __
  CI/CD            | __ ver __                 | __
  Observability    | __ ver __                 | __

--- SECTION: Component Architecture ---
  [Each deployable unit / bounded context / major module found in repo structure or docs]
  • Component: __ | Type: Service/Module/Library/DB/Queue | Responsibility: __
    Technology: __ | Exposes: __ | Consumes: __ | Repo/Path: __

--- SECTION: Key Interaction Flows ---
  [Extract primary happy-path flows from API routes, code, sequence diagrams, or architecture docs.]
  [Format: one-line ASCII arrow summary THEN numbered steps. Extract 2 flows if the system has multiple modes (e.g. Frontend + Batch).]

  FLOW 1 — Name: __ (e.g. Single-Document Frontend Processing)
  ASCII: [Stage 1] → [Stage 2] → [Stage 3] → ... → [Final Output]
  Step 1: Actor/Component — Action — Input — Output
  Step 2: ...
  Step 3: ...
  [Continue until the flow completes.]

  FLOW 2 — Name: __ (e.g. Batch / Async Processing — if present)
  ASCII: [Stage 1] → [Stage 2] → ...
  Step 1: ...

--- SECTION: Architecture Decision Records (ADRs) ---
  [From /adr, /docs/decisions, Confluence, code comments, or design tickets]
  • ADR-001 | Date: __ | Title: __ | Context: __ | Decision: __ | Alternatives: __ | Rationale: __ | Status: Accepted/Proposed/Deprecated/Superseded

--- SECTION: Non-Functional Requirements (NFRs) ---
  [From README SLAs, Jira NFR tickets, performance test configs, architecture docs]
  • Category: Performance/Availability/Scalability/Security/Compliance/Data Retention/Cost
    Requirement: __ | Target / SLA: __ | Current Baseline (if known): __ | Measured By: __ | Priority: High/Med/Low

--- SECTION: Security & Compliance ---
  Auth mechanism:          __ (OAuth2 / OIDC / JWT / SAML / API Key / mTLS / other)
  Authorisation model:     __ (RBAC / ABAC / ACL / other)
  Data encryption at rest: __ (yes/no — algorithm if found)
  Data encryption transit: __ (TLS version)
  Compliance requirements: __ (GDPR / SOC2 / HIPAA / PCI-DSS / ISO27001 / none found)
  Secret management:       __ (Vault / AWS Secrets / GCP Secret Manager / K8s Secrets / other)
  Vulnerability scanning:  __ (tool + frequency)

--- CONDITIONAL SECTION: ML/AI Projects only (skip if not ML/AI project) ---
  Model type:              __ (LLM / classification / regression / recommendation / CV / other)
  Training framework:      __ (PyTorch / TensorFlow / scikit-learn / HuggingFace / other)
  Serving infrastructure:  __
  Model versioning:        __ (MLflow / DVC / Weights&Biases / other)
  Data pipeline:           __
  Evaluation metrics:      __

--- CONDITIONAL SECTION: Microservices only (skip if monolith) ---
  Service discovery:       __
  API gateway:             __
  Inter-service comm.:     __ (REST / gRPC / event-driven / hybrid)
  Distributed tracing:     __
  Circuit breaker pattern: __

--- SECTION: Error & Edge Cases ---
  [Top 3 critical error paths from code, bug tickets, or error handling docs]
  • Scenario: __ | Trigger: __ | System Response: __ | Recovery: __

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  2. CODEBASE KB & CHANGE VERSIONING
# ══════════════════════════════════════════════════════════════════════════════
CODEBASE_KB = f"""
TASK: Extract all information needed to fill the Codebase Knowledge Base & Change Versioning Document.

SOURCE PRIORITY:
  1. Git metadata (remote URL, branches, tags, commit log, PR/MR history)
  2. CHANGELOG.md / CHANGELOG.rst / HISTORY.md / release notes
  3. Package manifests (package.json, requirements.txt, pom.xml, go.mod, Cargo.toml, build.gradle)
  4. ADR files (/adr, /docs/decisions, /architecture/decisions)
  5. Code comments (TODO / FIXME / HACK / DEBT / OPTIMIZE)
  6. Ticket system (tech-debt labels, dependency tickets, spike tickets)

{_DETECT}

--- SECTION: Repository Details ---
  Repo URL:                 __
  Primary Branch:           __
  Default Merge Strategy:   __ (merge commit / squash / rebase)
  Total Contributors:       __
  Language(s):              __
  Framework(s):             __
  Monorepo or Polyrepo:     __
  CI/CD Pipeline file(s):   __ (path and tool)
  Artifact Registry:        __ (Docker Hub / ECR / Nexus / GitHub Packages / other)
  Package Manager:          __ (npm / pip / maven / gradle / cargo / go modules / other)

--- SECTION: Branching Strategy ---
  Model:  __ (Git Flow / Trunk-Based / GitHub Flow / GitLab Flow / Scaled Trunk / Custom)
  Evidence basis: __
  • Branch type: __ | Pattern: __ | Purpose: __ | Merge into: __ | Policy: __

--- SECTION: Versioning Scheme ---
  Scheme:               __ (SemVer / CalVer / custom)
  Current version:      __
  Release cadence:      __ (weekly / bi-weekly / monthly / on-demand / continuous)
  Latest tag:           __

--- SECTION: Change Log ---
  [Last 10 meaningful entries. SKIP pure merge commits and automated version-bump commits.]
  • Date: __ | Version: __ | PR/Commit: __ | Author: __ | Type: Feature/Fix/Refactor/Config/Docs/Security/Performance | Summary: __ | Breaking: Yes/No

--- SECTION: Architecture Decision Records (ADRs) ---
  • ADR #: __ | Date: __ | Title: __ | Decision: __ | Status: Accepted/Proposed/Superseded/Deprecated | Supersedes: __

--- SECTION: Dependency Registry ---
  [ALL direct dependencies from manifest files. Flag any with known CVEs or outdated major versions.]
  • Package: __ | Version (pinned): __ | License: __ | Type: Direct/Dev/Transitive | Risk: Low/Med/High | CVE: __ | Last Updated: __

--- SECTION: Technical Debt Register ---
  [From TODO/FIXME/HACK/DEBT code comments, debt-labelled tickets, architecture known-issues]
  • ID: TD-001 | Location (file:line or ticket): __ | Description: __ | Component: __
    Severity: High/Med/Low | Estimated Effort: __ (hrs/days/SP) | Target Sprint/Version: __ | Owner: __

--- SECTION: Code Quality Metrics (if found in CI reports or config) ---
  Test coverage:          __%  (tool: __)
  Static analysis tool:   __   (rules profile: __)
  Lint rules:             __
  Code duplication:       __%  (tool: __)
  Known open code smells: __

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  3. CPDD — COMPREHENSIVE PROJECT DEFINITION DOCUMENT
# ══════════════════════════════════════════════════════════════════════════════
CPDD = f"""
TASK: Extract all information to fill the Comprehensive Project Definition Document (CPDD).
      This is the project charter — captures why, what, who, scope, and success criteria.

SOURCE PRIORITY:
  1. Project-level docs (README, project charter, kickoff deck, project wiki page)
  2. Ticket system (project metadata, epic descriptions, milestones/versions, sprint goals)
  3. Git (repository description, topics/tags, release notes, README)
  4. Any roadmap, OKR, or strategic document found in context

{_DETECT}

--- SECTION: Project Identity ---
  Project Name:         __
  Project Code / ID:    __
  Business Unit / Org:  __
  Executive Sponsor:    __
  Product Owner / PM:   __
  Tech Lead / Architect:__
  Start Date:           __
  Target Go-Live / End: __
  Budget:               __
  Priority:             __ (Critical / High / Medium / Low)
  Project Phase:        __ (Discovery / Planning / Development / Testing / Delivery / Maintenance)

--- SECTION: Business Problem & Objectives ---
  [One row per distinct objective. Extract from epic descriptions, project brief, OKRs, README motivation.]
  • Business Problem: __ | Desired Outcome: __ | Success Metric: __ | Baseline (current state): __

--- SECTION: Stakeholders ---
  [From ticket assignees, PR reviewers, project members, README contributors, org charts]
  • Name: __ | Role: __ | Organisation / Dept: __ | Responsibility: __
    Engagement Level: Accountable / Responsible / Consulted / Informed | Decision Authority: Yes/No

--- SECTION: Scope — IN ---
  [Features, modules, user types, or systems explicitly included — from epics, sprint goals, README]
  • __

--- SECTION: Scope — OUT OF SCOPE ---
  [Explicitly excluded — from "won't do" tickets, README limitations, known deferrals, stakeholder comments]
  • __

--- SECTION: Requirements Summary ---
  [High-level requirements only — link to tickets/epics, not full detail]
  • REQ-001 | Type: Functional/Non-Functional/Compliance | Description: __ | Source: __ | Priority: MoSCoW

--- SECTION: Deliverables & Milestones ---
  [Agile: sprints/releases. Waterfall: phases/gates. SAFe: PIs. Shape Up: cycles.]
  • Milestone / Phase: __ | Deliverable: __ | Owner: __ | Target Date: __ | Status: Not Started/In Progress/Done/At Risk

--- SECTION: Assumptions ---
  • __ (what must be true for the project to succeed as planned)

--- SECTION: Constraints ---
  • Type: Budget/Time/Technology/Regulatory/Resource | Constraint: __ | Impact if Violated: __

--- SECTION: External Dependencies ---
  • Dependency: __ | Type: Team / API / Vendor / 3rd Party / Regulatory | Owner: __ | Due: __ | Risk: __

--- SECTION: Top Risks Summary ---
  [High-level only — full detail in Risk Register]
  • Risk: __ | P: H/M/L | I: H/M/L | Score: __ | Owner: __ | Mitigation headline: __

--- SECTION: Budget & Resource Summary ---
  Total budget:           __
  Team size:              __
  Key roles & headcount:  __
  External vendor cost:   __

--- SECTION: Approval & Sign-Off ---
  • Role: __ | Name: __ | Sign-off Required: Yes/No

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  4. DEFINITION OF DONE (DoD)
# ══════════════════════════════════════════════════════════════════════════════
DOD = f"""
TASK: Extract and VALIDATE project-specific Definition of Done criteria.
      Compare actual project configuration against industry defaults.
      Flag gaps, overrides, and project-specific additions.

SOURCE PRIORITY:
  1. DoD wiki page / Confluence / Notion DoD document
  2. Branch protection rules (GitHub/GitLab/Bitbucket settings)
  3. CI/CD pipeline YAML (quality gates, required checks)
  4. Test config files (.sonarqube, jest.config.js, pytest.ini, .coveragerc, codecov.yml)
  5. PR/MR templates (.github/pull_request_template.md, .gitlab/merge_request_templates/)
  6. Sprint agreement comments in ticket system
  7. CONTRIBUTING.md / DEVELOPMENT.md

{_DETECT}

━━━━ VALIDATION MODE ━━━━
For each default criterion below, find the project's ACTUAL configured value.
Report the real value even if it matches the default. Never skip a row.

--- SECTION: Default Criteria Validation ---
  Default D1: Unit test coverage ≥ 80%
    Project actual: __% (source file: __)  | Status: Matches / Overrides / Not Configured [NA]

  Default D2: PR/MR requires ≥ 1 approval before merge
    Project actual: __ approvals  (source: branch protection / CI)  | Status: Matches / Overrides / Not Configured

  Default D3: Static analysis / linter must pass (no new violations)
    Tool used: __ | Rules profile: __ | Enforced in CI: Yes/No  | Status: Matches / Overrides / Not Configured

  Default D4: All automated tests green (unit + integration) before merge
    Test command: __ | Runs on: every push / PR only / manual  | Status: Matches / Overrides / Not Configured

  Default D5: Regression suite green before release / deployment
    Suite name/path: __ | Trigger: __  | Status: Matches / Overrides / Not Configured

  Default D6: No Critical or High security vulnerabilities (SAST/SCA)
    Tool: __ | Scan trigger: __  | Status: Matches / Overrides / Not Configured

--- SECTION: CI/CD Quality Gates ---
  [Every automated check that BLOCKS merge or deployment — extract from all CI YAML files]
  • Gate name: __ | Tool: __ | Checks: __ | Pass condition: __ | Blocks: PR Merge / Deploy / Both

--- SECTION: PR / MR Policy ---
  Min approvers required:      __
  Mandatory reviewers (CODEOWNERS / required reviewers): __
  Auto-merge allowed:          Yes / No | Conditions: __
  Draft PR / WIP policy:       __
  PR template enforced:        Yes / No | Template location: __

--- SECTION: Branch Protection Rules ---
  Protected branches:          __
  Rules applied:               __ (require reviews / status checks / linear history / signed commits)
  Force-push allowed:          Yes / No

--- SECTION: Story-Level DoD — Project Additions ---
  [Any criteria beyond D1–D6 that must be met before a story/ticket is closed]
  • __

--- SECTION: Sprint-Level DoD — Project Additions ---
  [Criteria that must be met at end of sprint / iteration / cycle]
  • __

--- SECTION: Release-Level DoD — Project Additions ---
  [Gates required before any production deployment]
  • __

--- SECTION: Sign-Off Requirements ---
  Story sign-off by:           __ (role)
  Sprint sign-off by:          __ (role)
  Release sign-off by:         __ (roles — all must approve)

--- SECTION: DoD Compliance Gaps ⚠ ---
  [CRITICAL: Flag every default criterion that has NO evidence of configuration in this project]
  • GAP: __ | Risk: __ | Recommendation: add __ to your DoD and enforce in CI

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  5. DEFINITION OF READY (DoR)
# ══════════════════════════════════════════════════════════════════════════════
DOR = f"""
TASK: Extract project-specific Definition of Ready criteria.
      Map to INVEST principles. Identify actual sprint-entry gates used by this team.

SOURCE PRIORITY:
  1. DoR wiki page / Confluence / Notion DoR document
  2. Ticket system — story templates, required fields, sprint planning comments
  3. PR template / CONTRIBUTING.md (story criteria before dev starts)
  4. Refinement meeting notes / sprint retrospective action items referencing DoR
  5. Ticket field configuration (mandatory fields in Jira/Linear/ADO before moving to "Ready")

{_DETECT}

--- SECTION: Estimation ---
  Estimation method:            __ (Story Points / T-shirt / Hours / #NoEstimates / Flow-based)
  Scale used:                   __ (Fibonacci: 1,2,3,5,8,13,21 / Linear / Custom)
  Estimation ceremony:          __ (Planning Poker / Async / Team vote / PM-assigned)
  Max size for single work item:__ (beyond this → must be split)
  Who estimates:                __ (whole team / dev team / PO-set / other)

--- SECTION: Work Item Format ---
  Format used:      __ (As a [role] I want [goal] so that [benefit] / Job Story / Goal-oriented / free-form)
  Example (real or template from context — anonymise sensitive data): __
  Required fields before "Ready" status:
  [Fields the team/tool enforces before a ticket can enter sprint — from Jira field config, Linear workflow, ADO rules]
  • Field: __ | Mandatory: Yes/Conditional | Checked by: Tool/Human | Why: __

--- SECTION: Acceptance Criteria Standard ---
  Format:           __ (Given/When/Then · Bullet points · Checklist · Mixed · Not standardised)
  Min AC required:  __ criteria per story
  Who writes AC:    __ (PO / Dev / Both in refinement)
  Example from context (anonymise): __

--- SECTION: Design & UX Readiness ---
  Design tool:                  __ (Figma / Sketch / Zeplin / Balsamiq / Adobe XD / none)
  Required before sprint entry: Yes / No / Conditional (only for UI stories)
  Approval needed from:         __
  Asset handoff process:        __

--- SECTION: Technical Readiness ---
  API contract required:        Yes / No / Conditional
  Contract format:              __ (OpenAPI/Swagger / Postman Collection / gRPC proto / AsyncAPI / none)
  DB schema / migration plan:   __ (required before dev: Yes/No)
  Technical spike required:     __ (when: unknown tech / high complexity / >__ points)
  Architecture review needed:   __ (threshold: __)

--- SECTION: Dependency Policy ---
  Dependency tracking tool:     __ (Jira link type / GitHub blocked-by / Linear dependency / other)
  Policy:                       __ (all deps resolved before sprint / known deps acceptable / no policy)
  Dependency owner:             __
  Escalation path:              __

--- SECTION: Test Data & Environment ---
  Test data available before sprint: Yes / No / Conditional
  Test environment:             __ (shared / dedicated / ephemeral / local only)
  Environment provisioning lead time: __

--- SECTION: INVEST Compliance Check ---
  [For each INVEST criterion, does this project have an explicit mechanism to enforce it?]
  Independent: __ (mechanism: __ / not enforced)
  Negotiable:  __ (mechanism: __ / not enforced)
  Valuable:    __ (mechanism: business value field / MoSCoW / not enforced)
  Estimable:   __ (mechanism: __ / not enforced)
  Small:       __ (max size policy: __ / not enforced)
  Testable:    __ (mechanism: AC required / not enforced)

--- SECTION: Readiness Gate / Score ---
  Scoring model used:           __ (binary checklist / weighted score / no formal model)
  Minimum threshold:            __ (e.g. all mandatory items ticked / score ≥ 7/10)
  Who can override / waive:     __
  What happens to not-ready stories: __ (kicked back to backlog / refined in planning / PM decision)

--- SECTION: Project-Specific DoR Additions ---
  [Any gate unique to this project — compliance sign-offs, security review, legal clearance, etc.]
  • __

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  6. RELEASE & DEPLOYMENT RUNBOOK  (ITIL v4 / SRE)
# ══════════════════════════════════════════════════════════════════════════════
RUNBOOK = f"""
TASK: Extract all information to fill the Release & Deployment Runbook.
      Target: the LATEST tagged release or the NEXT planned release in context.

SOURCE PRIORITY:
  1. CHANGELOG / release notes / GitHub Releases / GitLab Releases
  2. CI/CD pipeline YAML (deployment workflow steps, environment matrix)
  3. Deployment scripts (Makefile, deploy.sh, Ansible playbooks, Helm charts, Terraform)
  4. Ticket system (release version, fix-version tickets, deployment tasks, CAB tickets)
  5. Kubernetes manifests / docker-compose / ECS task definitions
  6. Runbook docs / Confluence deployment pages / Notion runbooks

{_DETECT}

--- SECTION: Release Identity ---
  Release version:       __
  Release type:          __ (Major breaking / Minor feature / Patch fix / Hotfix / Emergency)
  Git tag / branch:      __
  Planned deploy window: __ (date, time, timezone)
  Rollback deadline:     __ (point of no return)
  Change ticket / CAB #: __
  CAB approver:          __
  Deployment team:       __
  Communication channel: __ (Slack channel / Teams / Bridge line)

--- SECTION: Changes Included ---
  [All tickets with this fix-version, or commits since the last release tag]
  • Ticket: __ | Type: Feature/Bug/Security/Config/Docs/Perf | Summary: __
    Risk: Low/Med/High | Test evidence: __ | DB change: Yes/No

--- SECTION: Environment Topology ---
  [All environments in the deployment pipeline with their details]
  • Env: __ | URL: __ | Region: __ | Provider: AWS/GCP/Azure/On-prem/other | Access: __

--- SECTION: Deployment Pipeline ---
  [Extract every stage from CI/CD YAML. If using GitOps include sync steps.]
  Stage: __ | Steps:
  • Step: __ | Command/Action: __ | Expected result: __ | Timeout: __ | Owner: __ | ☐

  [Repeat for each stage: Build → Test → Stage Deploy → Smoke Test → Approval Gate → Prod Deploy → Verify]

--- SECTION: Pre-Release Checklist ---
  [All gates that must be green BEFORE the deployment window opens]
  • Criterion: __ | Verified By: __ | Evidence: __ | ☐ Done

--- SECTION: Database Changes ---
  Migration scripts:     __ (location, tool: Flyway/Liquibase/Alembic/manual/none)
  Backup taken:          Yes / No / NA
  Rollback migration:    __ (script location / manual steps / irreversible — note if so)
  Estimated duration:    __

--- SECTION: Feature Flags ---
  [Any feature flags / toggles for this release]
  • Flag name: __ | Service: __ | Default state: On/Off | Enable for: __% / All / Specific segments

--- SECTION: Post-Deploy Verification ---
  [Smoke tests, health checks, synthetic monitors to run immediately after deploy]
  • Check: __ | Command / URL: __ | Expected result: __ | Timeout: __ | Owner: __

--- SECTION: Monitoring & Alerting During Deploy ---
  Dashboard to watch:    __
  Key metrics to monitor:__
  Alert thresholds that indicate rollback: __
  Observation window:    __ minutes post-deploy before declaring stable

--- SECTION: Go / No-Go Decision ---
  Decision point:        __ (time/trigger)
  Decision makers:       __ (roles required)
  Criteria for Go:       __
  Criteria for No-Go:    __

--- SECTION: Rollback Plan ---
  Trigger conditions:    __
  Rollback steps:
  • Step: __ | Command/Action: __ | Owner: __ | ☐
  DB rollback process:   __
  Estimated rollback time: __
  Who authorises rollback: __

--- SECTION: Communications Plan ---
  Stakeholder notification — before deploy: __ (channel, message template)
  Stakeholder notification — after success: __
  Stakeholder notification — if rollback:   __

--- SECTION: Key Contacts ---
  • Role: __ | Name: __ | Slack/Phone: __ | Escalation level: L1/L2/L3

--- CONDITIONAL SECTION: Kubernetes / Container Deploy only ---
  Helm chart / manifest location: __
  Rollout strategy:               __ (RollingUpdate / Blue-Green / Canary)
  Canary percentage:              __
  Health check probes:            __

--- CONDITIONAL SECTION: Serverless / Cloud Functions only ---
  Function names:    __
  Cold start concern: Yes / No
  Traffic shifting:   __ (Lambda aliases / Cloud Run revisions / other)

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  7. RISK REGISTER  (ISO 31000 · PMBOK)
# ══════════════════════════════════════════════════════════════════════════════
RISK_REGISTER = f"""
TASK: Identify, score, and document ALL project risks found in the RAG context.
      Cast a wide net — risks appear in many forms across many sources.

SOURCE PRIORITY:
  1. Dedicated risk register / risk wiki / Confluence risk page
  2. Ticket system: tickets labelled risk / blocker / impediment / dependency / spike
  3. Retrospective notes (What could go wrong / Impediments raised)
  4. Git: TODO/FIXME/HACK comments with risk language, security scan reports
  5. Architecture docs: known limitations, scalability warnings, single points of failure
  6. README: warnings, known issues, limitations sections
  7. Epic descriptions: any "risk" or "assumption" language

RISK SCORING SCALE:
  Probability: 1=Rare  2=Unlikely  3=Possible  4=Likely  5=Almost Certain
  Impact:      1=Negligible  2=Minor  3=Moderate  4=Major  5=Critical
  Score = P × I
  Rating: 1–4=Low(🟢)  5–9=Medium(🟡)  10–19=High(🔴)  20–25=Critical(⛔)

RISK CATEGORIES:
  Technical · Schedule · Resource · Budget · External · Compliance/Legal ·
  Security/Cyber · Data · Vendor · Stakeholder · Scope · Quality · Environmental

{_DETECT}

--- SECTION: Risk Register ---
  [Extract EVERY risk signal found. Do not filter or dismiss. Score each one.]
  [Format one block per risk:]

  Risk ID:      R-001
  Category:     __
  Source:       __ (ticket ID / file:line / doc section where risk was found)
  Description:  __ [one sentence: "Risk that <event> occurs, causing <consequence>"]
  Probability:  __ / 5  |  Basis: __
  Impact:       __ / 5  |  Basis: __
  Score:        __ (P×I)
  Rating:       🟢 Low / 🟡 Medium / 🔴 High / ⛔ Critical
  Owner:        __ (name or role)
  Mitigation:   __ [active steps being taken now]
  Contingency:  __ [if risk occurs, what is the response plan]
  Status:       Open / Mitigating / Accepted / Resolved / Transferred
  Review Date:  __

  [Repeat for each risk found — no maximum]

--- SECTION: Risks Not Scored (Requires Human Assessment) ---
  [Vague or high-ambiguity risk signals that need human to score and classify]
  • Source: __ | Raw signal: __ | Why not scored: __

--- SECTION: Risk Summary Dashboard ---
  Total identified:   __
  ⛔ Critical:        __ | Highest score: __ | ID: __
  🔴 High:            __ | IDs: __
  🟡 Medium:          __ | IDs: __
  🟢 Low:             __ | IDs: __
  Top 3 risks by score:
    1. R-__ | __ | Score: __
    2. R-__ | __ | Score: __
    3. R-__ | __ | Score: __

--- SECTION: Risk Trends ---
  New risks since last review:    __
  Risks resolved since last review: __
  Trending direction:             ↑ Increasing / → Stable / ↓ Decreasing

--- SECTION: Closed / Resolved Risks (Audit Trail) ---
  • ID: __ | Description: __ | Resolution: __ | Closed Date: __

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  8. STANDARD OPERATING PROCEDURE (SOP)  —  ITIL v4 / SRE
# ══════════════════════════════════════════════════════════════════════════════
SOP = f"""
TASK: Extract all information to fill the Standard Operating Procedure (SOP) document.
      This covers day-to-day operations, incident response, and runbook knowledge.

SOURCE PRIORITY:
  1. Dedicated runbook / SOP / playbook docs (Confluence / Notion / GitBook / GitHub Wiki)
  2. README (setup, run, troubleshoot sections)
  3. Deployment scripts, Makefile, docker-compose, IaC configs
  4. Monitoring config (Prometheus rules / Datadog monitors / PagerDuty / OpsGenie / CloudWatch alarms)
  5. Ticket system: incident tickets (P1/P2 labels), on-call tickets, post-mortem tickets
  6. CI/CD YAML (environment config, secret references, deployment steps)
  7. Kubernetes / Docker / ECS configs (resource limits, health checks, restart policies)

{_DETECT}

--- SECTION: Service Identity ---
  Service name:              __
  Service description:       __ (1–2 sentences — what does it do, who depends on it)
  Business criticality:      __ (Mission Critical / High / Medium / Low)
  RTO (Recovery Time Obj.):  __ (max acceptable downtime)
  RPO (Recovery Point Obj.): __ (max acceptable data loss)
  SLA uptime target:         __%
  When to use this SOP:      __ (trigger conditions)
  What is OUT of scope:      __

--- SECTION: Environments ---
  [All environments serving live traffic or used by this SOP]
  • Env: __ | URL / Endpoint: __ | Region: __ | Cloud / Hosting: __
    Access level: __ | Owner: __ | Deployed version: __ | Notes: __

--- SECTION: Team Contacts & Escalation Matrix ---
  [From PagerDuty / OpsGenie schedules, Confluence on-call page, README contact section]
  • Level: L1/L2/L3/Vendor | Role: __ | Name: __ | Contact: __ (Slack/phone/email)
    Hours: 24×7 / Business hours | Escalate after: __ min | Escalate when: __

--- SECTION: Access & Credentials ---
  *** NEVER record actual credentials — reference vault paths only ***
  • System: __ | Access method: SSH Key / API Key / DB conn string / OAuth token / SSO
    Secret location: __ (Vault path / AWS Secrets / GCP Secret Manager / K8s Secret name)
    MFA required: Yes / No | Access owner: __ | Rotation policy: __

--- SECTION: Standard Operational Procedures ---
  [Daily / routine operations — startup, shutdown, scaling, backup, cache flush, etc.]

  Procedure: __ (e.g. Application Startup)
  Trigger: __ (when to run this)
  Steps:
  • Step: __ | Command: __ | Expected output: __ | Timeout: __ | If fails: __

  [Repeat for each distinct operational procedure found]

--- SECTION: Deployment Procedure ---
  [Step-by-step from deployment docs / CI-CD / scripts]
  • Step: __ | Action: __ | Command: __ | Expected output: __ | Rollback if fails: __

--- SECTION: Incident Severity Model ---
  [From on-call policy, PagerDuty/OpsGenie config, SLA agreements, incident ticket labels]
  • Severity: P1/P2/P3/P4 | Definition: __ | Example: __ | Response SLA: __
    Notification channel: __ | Incident commander: __ | Escalation path: __

--- SECTION: Incident Response Playbook ---
  Steps (apply to ALL incidents first, then severity-specific steps):
  • Step: __ | Action: __ | Owner: __ | Tool used: __ | ☐

  P1-Specific steps:
  • __

  Post-incident:
  • Post-mortem required: Yes (P1/P2) / No (P3/P4)
  • Post-mortem SLA: within __ hrs/days

--- SECTION: Monitoring & Observability ---
  [From Prometheus rules, Datadog monitors, CloudWatch alarms, Grafana dashboards]
  • Metric: __ | Tool: __ | Normal range: __ | Warning threshold: __ | Critical threshold: __
    Dashboard: __ (URL) | Alert channel: __ | Auto-remediation: Yes/No

--- SECTION: Common Issues & Runbook ---
  [From past incident tickets, README troubleshooting, FAQ, FIXME comments]
  • Symptom: __ | Likely cause: __ | Diagnostic command: __ | Fix: __ | Ticket ref: __

--- SECTION: Scheduled Jobs & Cron Tasks ---
  [From crontab, Kubernetes CronJobs, CI schedules, Lambda scheduled events]
  • Job: __ | Schedule: __ | Action: __ | Expected duration: __ | Owner: __ | Alert if missed: __

--- CONDITIONAL SECTION: Kubernetes / Container Platforms ---
  Namespace(s):       __
  Key deployments:    __
  Resource quotas:    __
  HPA / autoscaling:  __
  Useful kubectl cmds: __

--- CONDITIONAL SECTION: Cloud Provider Specific ---
  Provider:           __
  Key services used:  __
  IAM roles / SAs:    __
  Cost anomaly alerts: __

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  9. SPRINT CEREMONY & RETROSPECTIVE LOG  (Scrum / Kanban / SAFe / Waterfall)
# ══════════════════════════════════════════════════════════════════════════════
SPRINT_LOG = f"""
TASK: Extract all information for the Sprint / Iteration / Cycle ceremony log.
      Works for: Scrum sprints · Kanban period reviews · SAFe PI ceremonies ·
                 Waterfall phase reviews · Shape Up cycle reviews.

SOURCE PRIORITY:
  1. Ticket system — active or most recently completed sprint/board data
     (sprint name, dates, tickets, points, assignees, status, velocity, retrospective board)
  2. Git — commits and PRs merged within the sprint date range
  3. Confluence / Notion — sprint review notes, retro boards, planning docs
  4. Retro tool exports (EasyRetro / Retrium / Miro / FunRetro / TeamRetro)
  5. Meeting notes / recorded decisions in any linked doc

SDLC MAPPING:
  Scrum sprint   → sprint goal, sprint planning, daily standups, review, retro
  Kanban         → throughput period, flow metrics, periodic review, continuous improvement
  SAFe           → PI objectives, team iteration, system demo, I&A workshop
  Waterfall      → phase name, phase goals, phase review meeting, lessons learned
  Shape Up       → cycle name, betting table outcomes, cool-down, retrospective

{_DETECT}

--- SECTION: Iteration Summary ---
  [Adapt field names to the detected SDLC — e.g. "Sprint" → "Cycle" / "Phase" / "Iteration"]
  Sprint / Iteration name:          __
  Sprint / Iteration number:        __
  Goal / Objective:                 __ (what the team committed to achieving)
  Start date:                       __
  End date:                         __
  Team name:                        __
  Team size (during this sprint):   __ people
  Capacity (available person-days): __
  Committed work items (count):     __
  Committed points / effort:        __
  Rolling average velocity (last 3):__
  Outcome:                          __ (Goal Met / Partially Met / Not Met / Cancelled)

--- SECTION: Committed Work Items ---
  [All tickets/cards in this sprint/iteration]
  • ID: __ | Title: __ | Type: Story/Bug/Task/Spike/Chore | Points/Size: __
    Assignee: __ | Status at close: Done / In Progress / Carried Over / Cancelled
    PR/commit link: __

--- SECTION: Carry-Over / Incomplete Items ---
  [Items committed but not completed]
  • ID: __ | Title: __ | Points: __ | Root cause of not completing: __
    Action: Re-commit to next sprint / Deprioritise / Split / Escalate

--- SECTION: Unplanned Work Added Mid-Sprint ---
  [Scope creep, emergency fixes, or unplanned tasks added after sprint started]
  • ID: __ | Title: __ | Type: __ | Points: __ | Reason added: __ | Impact on sprint goal: __

--- SECTION: Sprint Review / Demo ---
  [What was demoed, who attended, what was accepted / rejected]
  • Item: __ | Demo'd by: __ | Stakeholder attending: __
    Feedback: __ | Accepted: Yes / No / Conditional — condition: __

--- SECTION: Bugs Raised This Sprint ---
  [Bugs found during review, testing, or prod monitoring in this sprint period]
  • Bug ID: __ | Title: __ | Severity: P1/P2/P3/P4 | Found in: Story/Sprint review/Prod
    Assigned sprint: __ | Owner: __

--- SECTION: Retrospective ---
  Facilitation format: __ (Start/Stop/Continue · 4Ls · Mad/Sad/Glad · Sailboat · Custom)
  Facilitated by:      __
  Attendees:           __

  Went Well (keep doing):
  • __

  Needs Improvement (do differently):
  • __

  Action Items (committed improvements with owner & due date):
  • Action: __ | Owner: __ | Due: __ | Status: Open / In Progress / Done

--- SECTION: Sprint Metrics ---
  Points committed:                  __
  Points completed:                  __
  Points carried over:               __
  Carry-over rate:                   __% (carried/committed)
  Bugs found this sprint:            __
  Bugs closed this sprint:           __
  Bug escape rate to prod:           __
  Team availability:                 __% (actual/planned person-days)
  Velocity vs 3-sprint average:      __ (above / below / on target)
  Sprint goal met:                   Yes / No / Partial — detail: __

--- CONDITIONAL SECTION: SAFe only ---
  PI number:                         __
  PI Objectives status:              __ (committed / stretch / achieved)
  System demo outcome:               __
  Inspect & Adapt actions:           __

--- CONDITIONAL SECTION: Kanban / Flow-based only ---
  Throughput (items completed):      __
  Cycle time average:                __ days
  Lead time average:                 __ days
  Flow efficiency:                   __%
  WIP limit violations:              __

--- SECTION: Decisions & Agreements ---
  [Formal decisions made during ceremonies — from meeting notes, Slack decisions, Confluence]
  • #: __ | Decision: __ | Rationale: __ | Made by: __ | Date: __

--- SECTION: Impediments & Blockers ---
  [Any impediments raised during the sprint — from daily standup notes, tickets, retro]
  • Impediment: __ | Raised by: __ | Raised on: __ | Owner: __ | Status: Resolved/Open | Resolution: __

{_CONFIDENCE}
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  10. PROJECT EXPLANATION — NEW JOINER ONBOARDING GUIDE
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_EXPLANATION = (_DETECT + """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOCUMENT OBJECTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generate a comprehensive "Project Explanation & Onboarding Guide" that any new
engineer or stakeholder can read to fully understand the project within 30 minutes.
Extract from: README, ARCHITECTURE.md, docs/, app.py, requirements.txt,
shared/ module files, pipeline/ scripts, config/, Dockerfile(s), Terraform IaC.

--- SECTION: Project at a Glance ---
  [From README header, package.json/setup.py, Dockerfile labels, Terraform variables]
  Project Name:           __
  Project Code / Repo:    __
  Business Purpose:       __ (1 sentence — what does this system do?)
  Primary Users:          __ (who uses it — end-users, batch clients, internal teams)
  Tech Stack (summary):   __ (e.g. "Python 3.9 · FastAPI · Gemini AI · BigQuery · Cloud Run")
  Deployment Target:      __ (Cloud Run / Kubernetes / VM / Lambda / etc.)
  GCP / Cloud Project:    __ (prod project ID and test project ID)
  Python / Runtime Ver:   __
  Current Status:         __ (Production / Beta / Development / Deprecated)
  License:                __

--- SECTION: Why This Project Exists ---
  [From README Problem Statement, project charter, Confluence, Architecture Overview]
  • Business Problem: __ | Approach / Solution: __ | Success Metric / KPI: __
  [Add 1-2 more rows if multiple problem dimensions exist]

--- SECTION: System Architecture Overview ---
  [From ARCHITECTURE.md, docs/ARCHITECTURE.md, README architecture section]
  Overview: __ (2-3 sentences describing the high-level architecture)

  System modes / major components:
  • System Mode: __ | Description: __ | Entry Point: __ | Output: __
  [List all major operating modes — e.g. Frontend API + Batch + Admin]

--- SECTION: Data Processing Flow (Frontend) ---
  [From ARCHITECTURE.md, LabelProcessor.py, app.py, README data flow section]
  • Step #: __ | What Happens: __ | Key Module / File: __ | Input: __ | Output: __
  [Trace the full document → storage journey step by step]

--- SECTION: Batch Processing Flow ---
  [From BATCH_PIPELINE.md, pipeline/, README batch section]
  • Step #: __ | Component: __ | What It Does: __ | Input: __ | Output: __ | Script / Entry: __

--- SECTION: Codebase Structure ---
  [From README project structure, directory listing, module docstrings]
  • Folder / File: __ | What It Does: __ | Key Classes / Functions: __ | When To Touch It: __
  [List every top-level folder and critical files — aim for 10-15 rows]

--- SECTION: Key Concepts ---
  [From README glossary, ARCHITECTURE.md, merchant_id docs, module-level docstrings]
  • Concept: __ | What It Is: __ | Why It Matters Here: __ | Where To Find Code / Docs: __
  [Include: domain terms like merchant_id, OCR scans; technology choices like Gemini, BigQuery, tesseract;
   cloud patterns like Workload Identity; framework terms like Kubeflow, kfp, AppConfig]

--- SECTION: API Endpoints ---
  [From app.py routes, README API reference section, OpenAPI schema]
  • Method: __ | Endpoint: __ | Purpose: __ | Request Payload: __ | Response: __
  [List all routes — GET, POST, SSE endpoints, health check, docs]

--- SECTION: BigQuery Data Model ---
  [From shared/schema.py, shared/db_bq_connector.py, README database section]
  • Table: __ | Primary Key(s): __ | Key Columns: __ | Populated By: __ | Notes: __
  [List all BigQuery tables with their relationships]

--- SECTION: How To Run Locally ---
  [From README Quick Start / Installation, Dockerfile, requirements.txt, .env.example]
  • Step: __ | Action: __ | Command / Tool: __ | Expected Output: __ | Notes: __
  [Cover: clone → install system deps → install Python deps → set env vars → auth → run → test]

--- SECTION: Environment & Config Reference ---
  [From README Configuration, config/configurations.yml, app.py AppConfig, .env.example]
  • Variable / Config Key: __ | Description: __ | Example Value: __ | Required: __ | Source: __
  [Cover all env vars + key YAML config entries a developer needs to understand]

--- SECTION: Infrastructure & IAM ---
  [From Terraform main.tf (prod + test), README deployment section, CI/CD YAML]
  • GCP Resource: __ | Name / ID: __ | Purpose: __ | Managed By: __
  [List: Cloud Run services, GCS buckets, BigQuery dataset, Artifact Registry,
   Vertex AI resources, service accounts, IAM groups, Workload Identity pools]

--- SECTION: Contacts & Escalation ---
  [From README Contributing / Contact section, CODEOWNERS, team docs, Terraform IAM groups]
  • Role: __ | Name: __ | Slack / Email: __ | Escalate When: __
  [List all key roles: Tech Lead, Platform Engineer, AI Engineer, PM, Scrum Master, IAM Manager]

{_CONFIDENCE}
""").strip()


# ══════════════════════════════════════════════════════════════════════════════
#  PROGRAMMATIC ACCESS
# ══════════════════════════════════════════════════════════════════════════════
PROMPTS = {
    "architecture":       ARCHITECTURE,
    "codebase_kb":        CODEBASE_KB,
    "cpdd":               CPDD,
    "dod":                DOD,
    "dor":                DOR,
    "runbook":            RUNBOOK,
    "risk_register":      RISK_REGISTER,
    "sop":                SOP,
    "sprint_log":         SPRINT_LOG,
    "project_explanation": PROJECT_EXPLANATION,
}

PROMPT_META = {
    "architecture":  {"title": "1. Architecture & Design",                  "doc": "Architecture_and_Design_Template.docx",               "standard": "arc42 / C4"},
    "codebase_kb":   {"title": "2. Codebase KB & Change Versioning",        "doc": "Codebase_KB_Change_Versioning_Template.docx",         "standard": "Git Flow / SemVer"},
    "cpdd":          {"title": "3. CPDD — Project Definition Document",     "doc": "CPDD_Template.docx",                                 "standard": "PMI PMBOK / Project Charter"},
    "dod":           {"title": "4. Definition of Done",                     "doc": "Defination_Of_Done_Template.docx",                   "standard": "Scrum Guide / SRE"},
    "dor":           {"title": "5. Definition of Ready",                    "doc": "DOR_Template.docx",                                  "standard": "INVEST Model"},
    "runbook":       {"title": "6. Release & Deployment Runbook",           "doc": "Release_and_deployment_runbook_Template.docx",        "standard": "ITIL v4 / SRE"},
    "risk_register": {"title": "7. Risk Register & Mitigation",             "doc": "Risk_Register_and_Mitigation_Template.docx",         "standard": "ISO 31000 / PMBOK"},
    "sop":           {"title": "8. Standard Operating Procedure",           "doc": "SOP_Template.docx",                                  "standard": "ITIL v4 / SRE"},
    "sprint_log":          {"title": "9. Sprint Ceremony & Retrospective Log",       "doc": "Sprint_Ceremony_and_Retrospective_log_Template.docx", "standard": "Scrum Guide / SAFe / Kanban"},
    "project_explanation": {"title": "10. Project Explanation — Onboarding Guide",    "doc": "Project_Explanation_Template.docx",                 "standard": "Internal / arc42 / PMI"},
}


def get_full_prompt(key: str) -> str:
    """Return SYSTEM + PROMPT ready to send to LLM."""
    return SYSTEM + "\n\n" + PROMPTS[key]


def print_all():
    SEP  = "=" * 72
    THIN = "-" * 72
    print(SEP)
    print("  UNIVERSAL RAG PROMPTS  —  10 Document Templates")
    print("  Works with: Scrum · Kanban · SAFe · Waterfall · Shape Up · DevOps")
    print("  Sources:    Any Git host · Jira/Linear/ADO/GitHub Issues · Any CI/CD")
    print(SEP)
    print()
    print("-- SYSTEM INSTRUCTION -- (prepend to EVERY prompt) --")
    print(THIN)
    print(SYSTEM)
    print()
    for key, meta in PROMPT_META.items():
        print(SEP)
        print(f"  {meta['title']}")
        print(f"  Standard: {meta['standard']}  |  Doc: {meta['doc']}")
        print(SEP)
        print(PROMPTS[key])
        print()
    print(SEP)
    print(f"  Total: {len(PROMPTS)} prompts  |  Token usage per prompt: ~600–1200 tokens")
    print(SEP)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print_all()
    print()
    print("Quick test -- all prompts loaded:")
    for k, meta in PROMPT_META.items():
        chars = len(get_full_prompt(k))
        print(f"  {meta['title']:<45} {chars:>5} chars  (~{chars//4:>4} tokens)")
