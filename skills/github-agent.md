# Skill: `github_agent`

## Identity

| Field           | Value                                                                       |
| --------------- | --------------------------------------------------------------------------- |
| Agent name      | `github_agent`                                                              |
| Type            | Specialist sub-agent (exposed to root agents via `AgentTool`)               |
| Model           | `gemini-2.5-pro` (with `HttpRetryOptions(attempts=3)`)                      |
| Defined in      | [`agent_rag_template.py`](../agent_rag_template.py) lines 63–88 and         |
|                 | [`agent_security_template.py`](../agent_security_template.py) lines 51–76   |
| Optional        | **Yes.** Only deployed if a `GITHUB_PAT` is provided at install time.       |

The agent's definition is wrapped in `# __GITHUB_MCP_BEGIN__ … # __GITHUB_MCP_END__`
sentinel markers. When no PAT is configured, `initial-connector.sh` strips
the entire block (and the `__GITHUB_MCP_TOOLS__` line in `root_agent`) before
deploying — see lines 2243–2244 of the connector.

## Purpose

`github_agent` is the **GitHub repository specialist**. It connects to the
[GitHub Copilot MCP server](https://api.githubcopilot.com/mcp/) and exposes
its toolset to the root agent so Pulse can fetch:

- source code,
- pull requests,
- issues,
- repository documentation (READMEs, etc.),
- commit history.

It is used to **correlate findings with code** (security workflow) and to
**back documentation generation with up-to-date repository context** (SDLC
workflow).

## Tools

The agent has exactly **one tool**: an `McpToolset` that proxies the GitHub
MCP server.

```python
github_mcp_tool = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://api.githubcopilot.com/mcp/",
        headers={
            "Authorization": f"******",
            "X-MCP-Toolsets": "all",
            "X-MCP-Readonly": "true",
        },
    ),
)
```

Key configuration:

| Header              | Value          | Effect                                                        |
| ------------------- | -------------- | ------------------------------------------------------------- |
| `Authorization`     | `****** | Authenticates against GitHub using the PAT supplied at install. |
| `X-MCP-Toolsets`    | `all`          | Enables the full GitHub MCP toolset (repos, PRs, issues, …).  |
| `X-MCP-Readonly`    | `true`         | **Hard read-only mode.** The agent cannot create, edit, or delete anything on GitHub. |

`GITHUB_TOKEN` is substituted in place of `__GITHUB_PAT__` by
`initial-connector.sh` line 2216.

## System instruction

Identical in both templates:

> You are a GitHub repository specialist. Use the GitHub MCP tools
> to fetch code, pull requests, issues, and documentation from GitHub
> repositories. Provide detailed and accurate information from the
> repositories.

(See `agent_rag_template.py:83-85` and `agent_security_template.py:71-73`.)

## Behavioural rules

1. **Read-only.** The MCP server is started with `X-MCP-Readonly: true`. The
   agent must not attempt to mutate repositories.
2. **Be specific and accurate.** It should ground its answers in the actual
   contents fetched from GitHub, not in model knowledge.
3. **Scoped to connected repositories.** When `GITHUB_REPOS` is configured at
   install time, the orchestration prompts of the root agents append the
   list of repositories and instruct the team to use them as the *primary*
   source — see `initial-connector.sh` lines 2233–2236.

## Inputs and outputs

| Aspect       | Description                                                                  |
| ------------ | ---------------------------------------------------------------------------- |
| Typical input | A delegation from the root agent like *"Fetch the latest README and most recent merged PRs for repo `solomonpapathoti/pulse`."* |
| Output       | Structured information extracted from GitHub: file contents, PR/issue lists, diffs, commit metadata, etc. |

## Configuration

The agent reads its credentials from the literal `GITHUB_TOKEN` constant
substituted into the template. The repository list, when provided, is
injected by the connector into the **root agent**'s instruction (not into
`github_agent`'s own instruction):

```text
Connected GitHub repositories for documentation and code review:
${GITHUB_REPOS}. When going through documentation, code, and project
context, use these repositories as your primary sources.
```

(See `initial-connector.sh` line 2234.)

## Extension points

- **Toolset trimming.** Replace `X-MCP-Toolsets: all` with a comma-separated
  subset (e.g. `repos,pull_requests`) to reduce the surface area exposed to
  the model.
- **Read/write mode.** Removing `X-MCP-Readonly: true` enables write
  operations — **not recommended** without a strong human-in-the-loop guard.
- **Different MCP server.** Point `url` at a self-hosted MCP if the team
  cannot use `api.githubcopilot.com`.

## Security notes

- The PAT is embedded as a literal string in the deployed `agent.py`. It
  must therefore be a fine-grained token scoped only to the repositories the
  agent should see. Treat the deployed agent code as sensitive.
- The agent is intentionally **read-only** so that an attacker who manages
  to prompt-inject the agent cannot push or delete code.

## See also

- [`document-editor.md`](./document-editor.md) — root agent that uses
  `github_agent` to enrich SDLC documentation.
- [`security-monitor.md`](./security-monitor.md) — root agent that uses
  `github_agent` to correlate SCC findings with source code.
