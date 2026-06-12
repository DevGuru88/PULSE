# Skill: `rag_agent`

## Identity

| Field           | Value                                                                 |
| --------------- | --------------------------------------------------------------------- |
| Agent name      | `rag_agent`                                                           |
| Type            | Specialist sub-agent (exposed to root agents via `AgentTool`)         |
| Model           | `gemini-2.5-pro` (with `HttpRetryOptions(attempts=3)`)                |
| Defined in      | [`agent_rag_template.py`](../agent_rag_template.py) lines 51–61 and   |
|                 | [`agent_security_template.py`](../agent_security_template.py) lines 39–49 |
| Used by         | `root_agent` of both `document-editor` and `security-monitor` builds, |
|                 | and indirectly by `doc_manager_agent` (which references the same corpus) |

## Purpose

`rag_agent` is the **document retrieval specialist** of the Pulse platform. It
knows how to query the project's Vertex AI RAG corpus and return relevant
snippets from the internal knowledge base (SDLC docs, SOPs, architecture
docs, runbooks, sprint logs, etc.).

It is the agent the root orchestrator calls **first**, before generating new
documents or producing an answer that should be grounded in existing project
context. The orchestration prompts injected into both root agents make this
explicit:

> "**IMPORTANT: Before generating any documents, ALWAYS delegate to
> `rag_agent` first to search the RAG knowledge base …**" — see
> `initial-connector.sh` lines 2222 and 2250.

## Tools

The agent has exactly **one tool**:

### `retrieve_rag_documentation`

A `VertexAiRagRetrieval` tool wired to the project's RAG corpus.

```python
ask_vertex_retrieval = VertexAiRagRetrieval(
    name="retrieve_rag_documentation",
    description="Retrieve documents from the RAG knowledge base.",
    rag_resources=[rag.RagResource(rag_corpus=CORPUS_URI)],
    similarity_top_k=10,
    vector_distance_threshold=0.6,
)
```

| Parameter                  | Value             | Meaning                                                                 |
| -------------------------- | ----------------- | ----------------------------------------------------------------------- |
| `rag_corpus`               | `CORPUS_URI`      | The Vertex AI RAG corpus resource (substituted from `__CORPUS_RESOURCE_NAME__` at install time) |
| `similarity_top_k`         | `10`              | Up to 10 chunks are returned per query.                                 |
| `vector_distance_threshold`| `0.6`             | Only chunks whose vector distance is below 0.6 are considered relevant. |

The corpus is populated by:

- the **document-editor pipeline** (after a reviewer approves a doc on the
  `/documents` page of the Pulse dashboard), and
- the **scc-poller** (which writes security findings and remediation drafts
  into `pending-documents/`, also subject to human review).

## System instruction

The instruction is identical in both templates:

> You are a document retrieval specialist. Use the
> `retrieve_rag_documentation` tool to search the internal RAG knowledge base
> and return relevant information.
> Always call the tool before answering. If no relevant information is found,
> say so.

(See `agent_rag_template.py:57-59` and `agent_security_template.py:45-47`.)

## Behavioural rules

1. **Always call the tool before answering.** The agent must not answer from
   model knowledge alone.
2. **Be honest about gaps.** If the retrieval call returns nothing relevant,
   the agent must explicitly say so rather than fabricate content.
3. **Read-only.** This agent has no write capability — it cannot upload,
   modify, delete, or refresh corpus content.

## Inputs and outputs

| Aspect       | Description                                                                 |
| ------------ | --------------------------------------------------------------------------- |
| Typical input | A natural-language question or query from the root agent (e.g. *"Is there an existing Definition of Done for project X?"*). |
| Output       | A grounded answer assembled from the top-`k` RAG chunks, or an explicit "no relevant information found" message. |

## Configuration

The agent depends on three environment variables that are set near the top of
both templates:

```python
os.environ["GOOGLE_CLOUD_PROJECT"]   = project_id          # auto-detected
os.environ["GOOGLE_CLOUD_LOCATION"]  = "__REGION__"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
```

`CORPUS_URI` is substituted from `__CORPUS_RESOURCE_NAME__` by
`initial-connector.sh` during scaffolding (lines 2210).

## Extension points

- **Tune retrieval quality** by editing `similarity_top_k` and
  `vector_distance_threshold` in the templates.
- **Restrict to a specific corpus partition** by passing additional
  `RagResource` entries.
- **Change the model** by editing the `Gemini(model=…)` argument; both
  templates currently pin `gemini-2.5-pro`.

## See also

- [`document-editor.md`](./document-editor.md) — root agent that delegates to
  `rag_agent` first.
- [`security-monitor.md`](./security-monitor.md) — same delegation pattern
  for SCC findings.
- [`doc-manager-agent.md`](./doc-manager-agent.md) — uses the same corpus to
  decide what to (re)generate.
