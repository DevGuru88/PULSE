# Skill: `document-editor` root agent

## Identity

| Field           | Value                                                                |
| --------------- | -------------------------------------------------------------------- |
| Agent name      | `root_agent` (deployed as the **`document-editor`** application)     |
| Display name    | *SDLC Document Editor*                                               |
| Type            | Root agent / orchestrator (deployed to Vertex AI Agent Engine)       |
| Model           | `gemini-2.5-pro` (with `HttpRetryOptions(attempts=3)`)               |
| Defined in      | [`agent_rag_template.py`](../agent_rag_template.py) lines 172–189    |
| Wired up by     | `agents_setup` in [`initial-connector.sh`](../initial-connector.sh) lines 2173–2271 |

The deployed application is named `app` (`App(root_agent=root_agent, name="app")`).

## Purpose

The `document-editor` is the user-facing chat agent dedicated to **SDLC
documentation work**. Its job is to take natural-language requests from
project members and orchestrate the right specialist sub-agent for each
part of the answer:

1. **Look up existing context** in the project knowledge base.
2. **Pull live information from GitHub** (when wired in).
3. **Generate, refresh, or audit SDLC documents** through the document
   pipeline.

It is **always grounded** — it asks `rag_agent` first before generating new
content, and it never writes to the live RAG corpus on its own.

## Sub-agents (tools)

The root agent exposes its specialists via `AgentTool`:

```python
root_agent = Agent(
    name="root_agent",
    model=Gemini(model="gemini-2.5-pro", retry_options=...),
    instruction="""__AGENT_INSTRUCTION__""",   # see below
    tools=[
        AgentTool(agent=rag_agent),
        AgentTool(agent=github_agent),         # __GITHUB_MCP_TOOLS__
        AgentTool(agent=doc_manager_agent),
    ],
)
```

| Sub-agent           | Always present? | Skill file                                        |
| ------------------- | --------------- | ------------------------------------------------- |
| `rag_agent`         | Yes             | [`rag-agent.md`](./rag-agent.md)                  |
| `github_agent`      | Only if a GitHub PAT was provided at install time | [`github-agent.md`](./github-agent.md) |
| `doc_manager_agent` | Yes             | [`doc-manager-agent.md`](./doc-manager-agent.md)  |

When no PAT is available, the connector strips the GitHub block and the
`__GITHUB_MCP_TOOLS__` line before deploying.

## System instruction (verbatim, by build variant)

`initial-connector.sh` substitutes one of two strings for the
`__AGENT_INSTRUCTION__` placeholder, depending on whether GitHub MCP is
enabled.

### Variant A — GitHub MCP enabled (line 2222 of `initial-connector.sh`)

> You are the SDLC Document Editor — a knowledgeable assistant that
> orchestrates three specialist agents:
>
> 1. `rag_agent` — Searches the internal RAG knowledge base for relevant
>    project documentation.
> 2. `github_agent` — Fetches code, pull requests, issues, and
>    documentation from GitHub repositories.
> 3. `doc_manager_agent` — Manages the full SDLC document lifecycle:
>    detects the current project stage, generates stage-appropriate
>    documents (CPDD, DOR, Architecture, Risk Register, Codebase KB, DoD,
>    Runbook, SOP, Sprint Log, Project Explanation), uploads them to GCS,
>    and refreshes the RAG corpus.
>
> Follow these guidelines when answering:
>
> - **IMPORTANT: Before generating any documents, ALWAYS delegate to
>   `rag_agent` first to search the RAG knowledge base
>   (corpus: `${CORPUS_RESOURCE_NAME}`) for existing documentation.** Only
>   generate documents that are missing or outdated.
> - If the user asks to generate, update, check staleness of, or manage
>   SDLC documents, delegate to `doc_manager_agent`. It will detect the
>   project stage (from the value set on the Pulse dashboard, persisted in
>   `stage.json`), check the knowledge base for existing documents, and
>   only produce documents that are missing or stale. The agent should NOT
>   ask the user to confirm the stage when one is already stored.
> - If the user's query is about source code, code reviews, pull requests,
>   issues, repository structure, or technical documentation, also
>   delegate to `github_agent` to fetch relevant content from the
>   connected repositories.
> - When multiple agents return useful results, combine and synthesize the
>   information into a single coherent answer.
> - If a query is specifically about code implementation details, file
>   contents, or recent changes, prioritize results from `github_agent` as
>   it provides the most up-to-date information.
> - If no relevant information is found from any agent, say so clearly.
>
> RAG Knowledge Base corpus ID: `${CORPUS_RESOURCE_NAME}`

### Variant B — GitHub MCP disabled (line 2250)

> You are the SDLC Document Editor — a document management assistant that
> orchestrates two specialist agents:
>
> 1. `rag_agent` — Retrieves relevant project documentation from the
>    knowledge base.
> 2. `doc_manager_agent` — Manages the full SDLC document lifecycle:
>    detects the current project stage, generates stage-appropriate
>    documents (CPDD, DOR, Architecture, Risk Register, Codebase KB, DoD,
>    Runbook, SOP, Sprint Log, Project Explanation), uploads them to GCS,
>    and refreshes the RAG corpus.
>
> **IMPORTANT: Before generating any documents, ALWAYS delegate to
> `rag_agent` first to search the RAG knowledge base
> (corpus: `${CORPUS_RESOURCE_NAME}`) for existing documentation.** Only
> generate documents that are missing or outdated.
>
> If the user wants to generate, update, check staleness of, or manage
> SDLC documents, delegate to `doc_manager_agent`. It will detect the
> project stage from the value set on the Pulse dashboard (persisted in
> `stage.json`), check the knowledge base for existing documents, and only
> produce documents that are missing or stale. The agent should NOT ask
> the user to confirm the stage when one is already stored.
>
> If no relevant information is found, say so.
>
> RAG Knowledge Base corpus ID: `${CORPUS_RESOURCE_NAME}`

### Optional repository-context suffix (lines 2233–2236, 2261–2264)

If `GITHUB_REPOS` is set at install time, **either** variant gets a suffix
appended:

> Connected GitHub repositories for documentation and code review:
> `${GITHUB_REPOS}`. When going through documentation, code, and project
> context, use these repositories as your primary sources.

(For variant B the wording is the slightly shorter "Connected GitHub
repositories: …. Reference these repositories when discussing project
documentation and context.")

## Behavioural rules

1. **RAG-first.** Always call `rag_agent` before generating, updating, or
   answering questions about documentation.
2. **Stage authority.** Never ask the user to confirm the SDLC stage when
   `doc_manager_agent` (via `detect_project_stage`) returns one
   successfully.
3. **No direct corpus writes.** All document changes flow through
   `doc_manager_agent` → pending-review queue → human approval on
   `/documents`.
4. **Source priority for code questions.** Prefer `github_agent` for
   implementation details, file contents, and recent changes (variant A
   only).
5. **Synthesise.** When several specialists contribute, combine the
   answers into one coherent response rather than just stitching them
   together.
6. **Be honest about gaps.** If nothing relevant is found, say so.

## Typical workflows

### "Are our SDLC docs up to date for project Foo?"

```
root_agent
  ├─ rag_agent.retrieve_rag_documentation(...)        # discover existing docs
  └─ doc_manager_agent
        ├─ detect_project_stage()
        ├─ check_document_staleness()
        └─ (reports — no generation needed yet)
```

### "Move project Foo into PRE_RELEASE and refresh the docs."

```
root_agent
  ├─ rag_agent.retrieve_rag_documentation(...)        # check what already exists
  └─ doc_manager_agent
        ├─ detect_project_stage()
        ├─ set_project_stage("PRE_RELEASE")
        ├─ check_document_staleness()
        ├─ generate_documents(stage="PRE_RELEASE", exclude_docs=fresh_keys)
        └─ upload_docs_to_gcs(output_dir)
            → "Sent N documents for review. Open /documents."
```

### "What did PR #42 change in the auth flow?" (variant A)

```
root_agent
  ├─ rag_agent.retrieve_rag_documentation(...)        # any existing notes?
  └─ github_agent.<MCP tools>                         # fetch PR + diff
       → synthesised answer
```

## Configuration

Environment variables (set in `agent_rag_template.py:30-34`):

- `GOOGLE_CLOUD_PROJECT` — auto-detected from ADC.
- `GOOGLE_CLOUD_LOCATION` — substituted from `__REGION__`.
- `GOOGLE_GENAI_USE_VERTEXAI` — `"True"`.
- `GCS_DATA_BUCKET` — substituted from `__GCS_DATA_BUCKET__`.
- `CORPUS_RESOURCE_NAME` — substituted from `__CORPUS_RESOURCE_NAME__`.

Build artifacts copied next to the agent at scaffold time
(`initial-connector.sh:2191-2200`):

- `app/doc_pipeline_tool.py`
- `app/pipeline/` (entire package)
- `python-docx` and `lxml` added via `uv add`.

## Deployment

`initial-connector.sh::agents_setup`:

1. `uvx agent-starter-pack create document-editor -a adk -d agent_engine ...`
2. Copies `agent_rag_template.py` → `document-editor/app/agent.py`.
3. Copies `doc_pipeline_tool.py` and `pipeline/` into `document-editor/app/`.
4. Substitutes `__REGION__`, `__CORPUS_RESOURCE_NAME__`,
   `__GCS_DATA_BUCKET__`, optionally `__GITHUB_PAT__`, and
   `__AGENT_INSTRUCTION__`.
5. Builds + deploys (in parallel with `security-monitor`).
6. Registers the agent in the Pulse webapp (`webapp/main.py`).

## See also

- [`rag-agent.md`](./rag-agent.md)
- [`github-agent.md`](./github-agent.md)
- [`doc-manager-agent.md`](./doc-manager-agent.md)
- [`security-monitor.md`](./security-monitor.md) — the sibling root agent.
