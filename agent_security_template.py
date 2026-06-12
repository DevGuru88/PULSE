import os
import google.auth

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from google.adk.tools.retrieval.vertex_ai_rag_retrieval import VertexAiRagRetrieval
from vertexai.preview import rag
# __GITHUB_MCP_BEGIN__
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
# __GITHUB_MCP_END__

# environment setup
_, project_id = google.auth.default()

os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "__REGION__"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

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
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
