# Skill: `security-monitor` root agent

## Identity

| Field           | Value                                                                  |
| --------------- | ---------------------------------------------------------------------- |
| Agent name      | `root_agent` (deployed as the **`security-monitor`** application)      |
| Display name    | *Security Monitor*                                                     |
| Type            | Root agent / orchestrator (deployed to Vertex AI Agent Engine)         |
| Model           | `gemini-2.5-pro` (with `HttpRetryOptions(attempts=3)`)                 |
| Defined in      | [`agent_security_template.py`](../agent_security_template.py) lines 78–94 |
| Wired up by     | `agents_setup` in [`initial-connector.sh`](../initial-connector.sh) lines 2173–2271 |

The deployed application is named `app` (`App(root_agent=root_agent, name="app")`).

## Purpose

The `security-monitor` is a **GCP security assistant** that triages
Security Command Center (SCC) findings for the project. It is consumed by:

- the **scc-poller** sidecar
  ([`scc-poller/parser-poller.py`](../scc-poller/parser-poller.py)), which
  every five minutes pulls fresh SCC findings and asks this agent to
  produce a remediation draft, and
- the Pulse dashboard chat UI, when an engineer wants an interactive
  triage.

It is a **read-only analyst** — it does not generate or upload SDLC
documents, does not call `doc_manager_agent`, and never mutates anything in
GCS, GitHub, or the RAG corpus.

## Sub-agents (tools)

The root agent exposes its specialists via `AgentTool`:

```python
root_agent = Agent(
    name="root_agent",
    model=Gemini(model="gemini-2.5-pro", retry_options=...),
    instruction="""__AGENT_INSTRUCTION__""",
    tools=[
        AgentTool(agent=rag_agent),
        AgentTool(agent=github_agent),     # __GITHUB_MCP_TOOLS__
    ],
)
```

| Sub-agent      | Always present?                                   | Skill file                                |
| -------------- | ------------------------------------------------- | ----------------------------------------- |
| `rag_agent`    | Yes                                               | [`rag-agent.md`](./rag-agent.md)          |
| `github_agent` | Only if a GitHub PAT was provided at install time | [`github-agent.md`](./github-agent.md)    |

When no PAT is configured, the connector strips the GitHub MCP block and
the `__GITHUB_MCP_TOOLS__` line before deploying. **Note that this agent
deliberately does not include `doc_manager_agent`** — the security-monitor
template (`agent_security_template.py`) does not import the SDLC pipeline.

## System instruction (verbatim, by build variant)

`initial-connector.sh` substitutes one of two strings for the
`__AGENT_INSTRUCTION__` placeholder, depending on whether GitHub MCP is
enabled.

### Variant A — GitHub MCP enabled (line 2227 of `initial-connector.sh`)

> You are the Security Monitor — a GCP security assistant that orchestrates
> two specialist agents:
>
> 1. `rag_agent` — Searches the internal RAG knowledge base for existing
>    security documentation, SOPs, and project context.
> 2. `github_agent` — Fetches code, pull requests, issues, and
>    documentation from GitHub repositories to correlate findings with
>    source code.
>
> Your primary role is to analyze Google Cloud Security Command Center
> (SCC) findings and provide actionable security guidance.
>
> Follow these guidelines when answering:
>
> - When presented with an SCC finding, delegate to `rag_agent` first to
>   check for existing remediation SOPs, security reports, or related
>   documentation in the knowledge base.
> - If the finding relates to code, infrastructure-as-code, or repository
>   configuration, delegate to `github_agent` to fetch the relevant source
>   files, recent changes, or related pull requests.
> - For each finding, provide: (a) root cause analysis, (b) concrete
>   mitigation steps, (c) a remediation SOP, and (d) references to any
>   relevant knowledge base documentation.
> - When both agents return useful results, combine and synthesize the
>   information into a single coherent security assessment.
> - You are a read-only analyst — you do NOT create, edit, or upload
>   documents. Your role is to analyze, assess, and recommend.
> - If no relevant information is found from either agent, say so clearly
>   and provide general GCP security best-practice guidance.

### Variant B — GitHub MCP disabled (line 2255)

> You are the Security Monitor — a GCP security assistant that delegates
> to a specialist agent.
>
> Your primary role is to analyze Google Cloud Security Command Center
> (SCC) findings and provide actionable security guidance.
>
> Always delegate to `rag_agent` to search the knowledge base for existing
> security documentation, SOPs, and remediation guidance before answering.
>
> For each finding, provide: (a) root cause analysis, (b) concrete
> mitigation steps, (c) a remediation SOP, and (d) references to any
> relevant knowledge base documentation.
>
> You are a read-only analyst — you do NOT create, edit, or upload
> documents. Your role is to analyze, assess, and recommend.
>
> If no relevant information is found, say so and provide general GCP
> security best-practice guidance.

### Optional repository-context suffix (lines 2233–2236, 2261–2264)

When `GITHUB_REPOS` is configured, the connector appends:

> Connected GitHub repositories for documentation and code review:
> `${GITHUB_REPOS}`. When going through documentation, code, and project
> context, use these repositories as your primary sources.

(Variant B uses the shorter "Connected GitHub repositories: ….")

## Required output structure for every finding

Whichever variant is deployed, the agent must always return four sections
when asked to triage a finding:

1. **Root cause analysis** — what the finding actually means for this
   environment.
2. **Concrete mitigation steps** — actionable, ordered remediation.
3. **Remediation SOP** — a reusable, structured Standard Operating
   Procedure.
4. **References** — pointers to KB documents (returned by `rag_agent`)
   and, if available, to source files / PRs (returned by `github_agent`).

The scc-poller saves the agent's response into
`gs://$GCS_DATA_BUCKET/pending-documents/` so a reviewer can promote it
into the live KB through the dashboard's `/documents` page (see the
description in `initial-connector.sh:2152`).

## Behavioural rules

1. **RAG-first.** Always delegate to `rag_agent` before answering, to
   surface existing SOPs and prior remediations.
2. **Correlate with code** when applicable (variant A only) by delegating
   to `github_agent`.
3. **Read-only.** Never create, edit, or upload documents. The poller +
   dashboard handle persistence.
4. **No SDLC pipeline.** This agent has no access to
   `doc_manager_agent` or to `doc_pipeline_tool.py`.
5. **Synthesise** when multiple specialists return useful information.
6. **Fall back gracefully.** If no KB / repo context is found, provide
   general GCP security best practices and say so explicitly.

## Typical workflow (poller-driven)

```
SCC finding (every 5 minutes)
        │
        ▼
parser-poller.py  ──── prompt with finding ────► security-monitor (root_agent)
                                                  │
                                                  ├─ rag_agent      → existing SOPs / KB context
                                                  ├─ github_agent   → related code / PRs (if PAT set)
                                                  ▼
                          structured response: root cause + mitigation + SOP + refs
                                                  │
                                                  ▼
                              gs://$GCS_DATA_BUCKET/pending-documents/
                                                  │
                                                  ▼
                              reviewer approves on Pulse `/documents`
                                                  │
                                                  ▼
                              promoted into rag/docs/, RAG corpus refreshed
```

## Configuration

Environment variables (set in `agent_security_template.py:20-22`):

- `GOOGLE_CLOUD_PROJECT` — auto-detected from ADC.
- `GOOGLE_CLOUD_LOCATION` — substituted from `__REGION__`.
- `GOOGLE_GENAI_USE_VERTEXAI` — `"True"`.

`CORPUS_URI` is substituted from `__CORPUS_RESOURCE_NAME__` and used by
the embedded `rag_agent`. Unlike the document-editor build, this template
does **not** read `GCS_DATA_BUCKET` directly (the scc-poller owns the
GCS interaction).

## Deployment

`initial-connector.sh::agents_setup`:

1. `uvx agent-starter-pack create security-monitor -a adk -d agent_engine ...`
2. Copies `agent_security_template.py` → `security-monitor/app/agent.py`.
3. Substitutes `__REGION__`, `__CORPUS_RESOURCE_NAME__`, optionally
   `__GITHUB_PAT__`, and `__AGENT_INSTRUCTION__`.
4. Builds + deploys (in parallel with `document-editor`).
5. Registers the agent in the Pulse webapp.
6. The scc-poller (deployed separately by SECTION 17 of the connector,
   *Setup Security Pipeline*) starts polling SCC and forwarding findings
   to this agent every 5 minutes.

## See also

- [`rag-agent.md`](./rag-agent.md)
- [`github-agent.md`](./github-agent.md)
- [`document-editor.md`](./document-editor.md) — the sibling root agent.
- [`scc-poller/parser-poller.py`](../scc-poller/parser-poller.py) — the
  client that drives this agent on a schedule.
