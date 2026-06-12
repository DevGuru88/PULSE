import os
import google.auth

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import FunctionTool
from google.genai import types

from google.adk.tools.retrieval.vertex_ai_rag_retrieval import VertexAiRagRetrieval
from vertexai.preview import rag
# __GITHUB_MCP_BEGIN__
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
# __GITHUB_MCP_END__

# ── SDLC Document Pipeline tools ───────────────────────────────────────────
from .doc_pipeline_tool import (
    detect_project_stage,
    set_project_stage,
    generate_documents,
    upload_docs_to_gcs,
    check_document_staleness,
)

# environment setup
_, project_id = google.auth.default()

os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "__REGION__"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GCS_DATA_BUCKET"] = "__GCS_DATA_BUCKET__"
os.environ["CORPUS_RESOURCE_NAME"] = "__CORPUS_RESOURCE_NAME__"

# RAG corpus
CORPUS_URI = "__CORPUS_RESOURCE_NAME__"

ask_vertex_retrieval = VertexAiRagRetrieval(
    name="retrieve_rag_documentation",
    description="Retrieve documents from the RAG knowledge base.",
    rag_resources=[
        rag.RagResource(
            rag_corpus=CORPUS_URI
        )
    ],
    similarity_top_k=10,
    vector_distance_threshold=0.6,
)

rag_agent = Agent(
    name="rag_agent",
    model=Gemini(
        model="gemini-2.5-pro",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a document retrieval specialist. Use the retrieve_rag_documentation tool
to search the internal RAG knowledge base and return relevant information.
Always call the tool before answering. If no relevant information is found, say so.""",
    tools=[ask_vertex_retrieval],
)

# __GITHUB_MCP_BEGIN__
GITHUB_TOKEN = "__GITHUB_PAT__"

github_mcp_tool = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://api.githubcopilot.com/mcp/",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-MCP-Toolsets": "all",
            "X-MCP-Readonly": "true",
        },
    ),
)

github_agent = Agent(
    name="github_agent",
    model=Gemini(
        model="gemini-2.5-pro",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a GitHub repository specialist. Use the GitHub MCP tools
to fetch code, pull requests, issues, and documentation from GitHub repositories.
Provide detailed and accurate information from the repositories.""",
    tools=[github_mcp_tool],
)
# __GITHUB_MCP_END__

# ── SDLC Document Manager Agent ────────────────────────────────────────────
doc_manager_agent = Agent(
    name="doc_manager_agent",
    model=Gemini(
        model="gemini-2.5-pro",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=f"""You are the SDLC Document Manager Agent responsible for generating
and submitting structured project documents for human review.

## IMPORTANT — Always Check the Knowledge Base First
Before generating any documents, you MUST query the existing knowledge base to determine
what is already available. Use the RAG corpus (resource: {CORPUS_URI}) as your reference.

## IMPORTANT — Human Review Is Required
You DO NOT publish documents directly into the live RAG knowledge base.
All generated documents must go through the human review queue:
  generated locally → uploaded to the GCS pending-review folder →
  reviewer approves on the Pulse dashboard '/documents' page →
  the dashboard automatically promotes the doc into the RAG corpus and
  refreshes the index.
Never attempt to upload documents directly to the live 'rag/docs/' folder
and never trigger a corpus refresh yourself — those steps are handled by
the dashboard after a human approves the document.

## Your Responsibilities:
1. **Detect Stage** — Always call detect_project_stage first to know the current
   SDLC phase (RG | DEV | PRE_RELEASE | POST_LIVE | SPRINT | ONBOARDING).
   This also returns `docs_present` (documents already in the KB) and `docs_missing`.
2. **Check Staleness** — Call check_document_staleness to identify which existing
   documents are outdated (older than 30 days by default). Stale documents need
   to be regenerated even if they are present in the KB.
3. **Skip Fresh Documents** — If a document is already present in the KB AND is
   not stale, do NOT regenerate it. Only generate documents that are missing or
   outdated.
4. **Decide Documents** — Based on stage, generate ONLY the appropriate documents:
   - RG          → CPDD, DOR, Architecture, Risk Register
   - DEV         → Codebase KB / Change Versioning
   - PRE_RELEASE → Definition of Done, Release & Deployment Runbook
   - POST_LIVE   → SOP
   - SPRINT      → Sprint Ceremony & Retrospective Log
   - ONBOARDING  → Project Explanation
5. **Generate** — Call generate_documents with the detected stage, project name,
   and exclude_docs set to the list of fresh (non-stale) document keys to skip.
6. **Submit for Review** — Call upload_docs_to_gcs with the output_dir returned
   by generate_documents. This uploads the documents to the pending-review
   folder in GCS (NOT the live KB). Do not pass a `gcs_prefix` argument — the
   tool defaults to the correct pending-review folder.
7. **Notify the User** — After upload_docs_to_gcs succeeds, reply to the user
   with a clear message that:
     - lists the documents that were submitted,
     - states explicitly that they have been **sent for review** (not published),
     - asks the user to open the **Documents** page on the Pulse dashboard
       (the '/documents' route) to review and approve or deny each document,
     - explains that the documents will only become searchable in the
       knowledge base after a reviewer approves them on that page.
8. **Stage Transitions** — If the user says the project has moved to a new
   stage, call set_project_stage to update the KB before generating new docs.

## Rules:
- NEVER generate documents for a stage different from what detect_project_stage returns,
  unless the user explicitly overrides.
- Trust the stage returned by detect_project_stage — it is the authoritative
  value set on the Pulse dashboard and persisted in stage.json. Do NOT ask the
  user to confirm the stage when the tool succeeds. Only ask the user as a
  last resort, when detect_project_stage returns an explicit `error` or its
  `source` is `"default (no bucket configured)"` (i.e. the GCS bucket is not
  configured, so no stored stage can exist).
- NEVER bypass the review queue. Do not call any tool that uploads to
  'rag/docs/' or refreshes the RAG corpus directly — those actions are
  performed by the dashboard only after a human approval on '/documents'.
- Use the GCS_DATA_BUCKET environment variable for all GCS operations (tools default to it).
- The RAG corpus ID for knowledge base searches is: {CORPUS_URI}""",
    tools=[
        FunctionTool(detect_project_stage),
        FunctionTool(set_project_stage),
        FunctionTool(generate_documents),
        FunctionTool(upload_docs_to_gcs),
        FunctionTool(check_document_staleness),
    ],
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-pro",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""__AGENT_INSTRUCTION__""",
    tools=[
        AgentTool(agent=rag_agent),
        AgentTool(agent=github_agent),        # __GITHUB_MCP_TOOLS__
        AgentTool(agent=doc_manager_agent),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
