# Global Claude Context

## User Documentation

The user maintains a personal reference document at `/opt/docs/peachhouse-server-docs.md`. This is the user's own documentation for their system — not instructions for Claude. When the user references their docs or asks about their setup, this file may contain relevant context worth reading.

## Ollama MCP — Local LLM Delegation

An `ollama` MCP server is available via `/opt/mcp-tools/bin/mcp-ollama`, pointing at the desktop GPU proxy (`http://192.168.68.16:11435`). Use the `ask_model` tool directly — never via a subagent, as MCP tools are not available to subagents.

**Preferred model: `qwen2.5:7b`** — use this by default for all Ollama delegation.

**Available models (verify with `list_models` — changes as desktop syncs):**
- `qwen2.5:7b` — desktop GPU (RTX 2070 Super). Preferred choice.
- `dolphin-llama3:latest` — desktop GPU fallback.
- `llama3.2:1b` / `qwen2.5:1.5b-ctx32k` — server CPU fallback when desktop is off. Too small for most tasks.

**Important:** MCP tools from servers registered mid-session are not available until the next fresh session. If `ask_model` is not in the tool list, the server was registered this session — skip Ollama and do the task directly.

**Delegate to Ollama for** (self-contained tasks only — no conversation context needed):
- Summarising long log or config file contents before reasoning about them
- Simple text transformations (reformatting, extraction, normalisation)
- Generating repetitive boilerplate (Dockerfiles, compose snippets, cron entries)
- Drafting short natural-language strings (descriptions, labels)

**Keep on Claude for:**
- Anything requiring context from earlier in the conversation
- Code logic, debugging, architecture decisions
- Tasks where correctness matters and errors are costly
- Anything sensitive or security-related
