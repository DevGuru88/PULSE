# Pulse Agent Skills

This folder documents the **skills** of every agent that ships with the Pulse
personal showcase. Each markdown file captures, for one agent, the
information you need to understand, reproduce, extend, or audit it:

- the agent's identity and purpose,
- which model it runs on,
- which tools (and sub-agents) it can call,
- the system instructions / playbook it operates under,
- the inputs it expects and the outputs it produces,
- the rules and guard-rails it must respect,
- where in the codebase it is defined and how it is wired together at
  deployment time.

## Map of agents

Pulse deploys **two top-level (root) agents** on Vertex AI Agent Engine. Each
root agent orchestrates a small team of **specialist sub-agents** that are
exposed to it through `AgentTool`. The two root agents are scaffolded by
`initial-connector.sh` from the templates in this repository:

| Root agent (deployed app)         | Template file                                                | Specialist sub-agents it can call                |
| --------------------------------- | ------------------------------------------------------------ | ------------------------------------------------ |
| **document-editor** (SDLC Doc Editor) | [`agent_rag_template.py`](../agent_rag_template.py)          | `rag_agent`, `github_agent` *(opt.)*, `doc_manager_agent` |
| **security-monitor** (Security Monitor) | [`agent_security_template.py`](../agent_security_template.py) | `rag_agent`, `github_agent` *(opt.)*             |

> The `github_agent` is only wired in if a GitHub PAT is configured at install
> time — see `initial-connector.sh` (`__GITHUB_MCP_BEGIN__` / `__GITHUB_MCP_END__`
> markers in the templates).

## Skill files

| Skill file                                           | Agent             | Role                                                                |
| ---------------------------------------------------- | ----------------- | ------------------------------------------------------------------- |
| [`document-editor.md`](./document-editor.md)         | `root_agent` (document-editor build) | Top-level orchestrator for SDLC documentation tasks.        |
| [`security-monitor.md`](./security-monitor.md)       | `root_agent` (security-monitor build) | Top-level orchestrator for SCC finding triage and remediation. |
| [`rag-agent.md`](./rag-agent.md)                     | `rag_agent`       | Specialist that queries the Vertex AI RAG corpus.                   |
| [`github-agent.md`](./github-agent.md)               | `github_agent`    | Specialist that talks to GitHub through the GitHub MCP server.      |
| [`doc-manager-agent.md`](./doc-manager-agent.md)     | `doc_manager_agent` | Specialist that runs the full SDLC document lifecycle.            |

## How the agents are deployed

The `agents_setup` step in [`initial-connector.sh`](../initial-connector.sh)
(SECTION 18, around line 2155) does the following for each of the two root
agents:

1. Scaffolds a fresh ADK / Agent-Engine project with
   `uvx agent-starter-pack create <agent>`.
2. Copies the matching template (`agent_rag_template.py` for
   `document-editor`, `agent_security_template.py` for `security-monitor`)
   into `<agent>/app/agent.py`.
3. For `document-editor`, also copies `doc_pipeline_tool.py` and the entire
   `pipeline/` package into `<agent>/app/`, and adds `python-docx` + `lxml`
   as dependencies (used by the SDLC document pipeline).
4. Substitutes the placeholders in the template:
   - `__REGION__` → the GCP region
   - `__CORPUS_RESOURCE_NAME__` → the Vertex AI RAG corpus resource name
   - `__GCS_DATA_BUCKET__` → the GCS bucket holding RAG data and
     pending-review docs
   - `__GITHUB_PAT__` → the GitHub PAT (if provided)
   - `__AGENT_INSTRUCTION__` → the orchestration prompt (one of four
     variants, depending on `agent` × `GitHub MCP enabled?`)
5. If no PAT is configured, the GitHub MCP block (between
   `__GITHUB_MCP_BEGIN__` and `__GITHUB_MCP_END__`) and the
   `__GITHUB_MCP_TOOLS__` line are stripped out, and a RAG-only instruction
   variant is injected instead.
6. Builds and deploys the agent to Vertex AI Agent Engine (in parallel for
   both root agents), then registers it in the Pulse webapp via the
   `/api/agents` endpoint exposed by `webapp/main.py`.

For the verbatim instruction strings injected into each agent variant, see
the corresponding skill file's *System instruction* section.
